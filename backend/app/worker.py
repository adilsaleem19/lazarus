"""arq worker: the analyze_job pipeline (validate -> robots -> capture -> distill -> persist).

External stages (DNS, robots fetch, browser capture) are read from ctx with real
defaults, so tests inject fakes by overriding ctx keys.
"""

import asyncio
import uuid
from urllib.parse import urlsplit

import httpx
import sqlalchemy as sa
import structlog
from arq import cron
from arq.connections import RedisSettings

from app.agent.service import build_context, make_slug
from app.agent.service import run_agent as run_agent_default
from app.agent.validation import validate_records
from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.events import EventEmitter
from app.ingestion.capture import capture_page
from app.ingestion.distill import distill
from app.ingestion.robots import check_robots
from app.ingestion.urlguard import default_resolver, validate_target_url
from app.job_states import JobStatus, assert_transition
from app.logging import configure_logging
from app.models import Extractor, Job, LLMCall, PageSnapshot, utcnow
from app.sandbox import run_extractor

log = structlog.get_logger()


async def _respect_domain_rate(redis, host: str) -> None:
    """At most 1 request/second per target domain, shared across workers."""
    if redis is None:
        return
    for _ in range(20):
        if await redis.set(f"lazarus:domain-rate:{host}", "1", nx=True, px=1000):
            return
        await asyncio.sleep(0.25)


def _set_status(job: Job, new: JobStatus, reason: str | None = None) -> None:
    assert_transition(JobStatus(job.status), new)
    job.status = new.value
    if reason is not None:
        job.reason = reason


async def _run_agent_stage(
    run_agent, ctx, settings, job_id: str, context: dict, slug: str, emitter
):
    """Run the agent, streaming events, then persist its LLM calls and (if any) extractor."""
    sessionmaker = ctx["sessionmaker"]
    calls: list[dict] = []

    outcome = await run_agent(
        context=context,
        settings=settings,
        http=ctx.get("http"),
        emitter=emitter,
        on_call=calls.append,
        sandbox=ctx.get("sandbox"),
    )

    job_uuid = uuid.UUID(job_id)
    async with sessionmaker() as session:
        for call in calls:
            session.add(LLMCall(job_id=job_uuid, **call))
        if outcome.ok:
            records = outcome.records or []
            max_version = (
                await session.execute(
                    sa.select(sa.func.max(Extractor.version)).where(Extractor.slug == slug)
                )
            ).scalar()
            # A new version replaces the old one for this slug — the old row stays
            # for history but stops being served, refreshed, or counted in the cap.
            await session.execute(
                sa.update(Extractor)
                .where(Extractor.slug == slug, Extractor.status == "active")
                .values(status="superseded")
            )
            session.add(
                Extractor(
                    job_id=job_uuid,
                    slug=slug,
                    source_url=context["url"],
                    strategy=outcome.strategy,
                    target=outcome.target if outcome.strategy == "json_xhr" else None,
                    code=outcome.code or "",
                    record_schema=outcome.record_schema or {},
                    version=(max_version or 0) + 1,
                    sample=records[:5],
                    data=records,
                    description=outcome.description,
                    last_refreshed_at=utcnow(),
                )
            )
            await _evict_over_cap(session, settings)
        await session.commit()
    return outcome


async def _evict_over_cap(session, settings: Settings) -> None:
    """Keep at most max_active_extractors live; retire the least recently used."""
    await session.flush()  # the new extractor must be visible to the count
    actives = (
        (await session.execute(sa.select(Extractor).where(Extractor.status == "active")))
        .scalars()
        .all()
    )
    overflow = len(actives) - settings.max_active_extractors
    if overflow <= 0:
        return
    actives.sort(key=lambda e: _ensure_aware(e.last_accessed_at or e.created_at))
    for extractor in actives[:overflow]:
        extractor.status = "evicted"
        extractor.paused_reason = (
            f"evicted to stay under {settings.max_active_extractors} live APIs "
            "(least recently used)"
        )
        log.info("extractor_evicted", slug=extractor.slug)


async def analyze_job(ctx: dict, job_id: str) -> str:
    settings: Settings = ctx["settings"]
    sessionmaker = ctx["sessionmaker"]
    robots_check = ctx.get("robots_check", check_robots)
    capture = ctx.get("capture", capture_page)
    resolve = ctx.get("resolve", default_resolver)
    http: httpx.AsyncClient | None = ctx.get("http")

    emitter = EventEmitter(job_id, sessionmaker, ctx.get("redis"))

    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if job is None:
            log.warning("job_missing", job_id=job_id)
            return "missing"

        _set_status(job, JobStatus.ANALYZING)
        await session.commit()
        log.info("job_analyzing", job_id=job_id, url=job.url)
        await emitter.emit("analyzing", f"Waking the browser — loading {job.url}")

        try:
            url = validate_target_url(
                job.url, resolve=resolve, deny_hosts=settings.deny_hosts_set
            )
            host = urlsplit(url).hostname or ""

            await _respect_domain_rate(ctx.get("redis"), host)
            verdict = await robots_check(url, user_agent=settings.user_agent, client=http)
            if not verdict.allowed:
                _set_status(job, JobStatus.FAILED, reason=verdict.reason)
                await session.commit()
                await emitter.emit(
                    "failed", f"Blocked by robots.txt: {verdict.reason}",
                    data={"stage": "robots"},
                )
                log.info("job_blocked_by_robots", job_id=job_id, reason=verdict.reason)
                return "blocked"
            await emitter.emit(
                "robots_ok", "robots.txt allows this page", data={"status": verdict.status}
            )

            await _respect_domain_rate(ctx.get("redis"), host)
            result = await capture(url, settings)
            distilled = distill(result.final_html, max_tokens=settings.max_skeleton_tokens)

            session.add(
                PageSnapshot(
                    job_id=job.id,
                    final_html=result.final_html,
                    skeleton=distilled.skeleton,
                    token_estimate=distilled.token_estimate,
                    meta=distilled.meta,
                    xhr=result.xhr,
                    structures=distilled.structures,
                    robots_status=verdict.status,
                    robots_reason=verdict.reason,
                )
            )
            await session.commit()  # snapshot durable before the (long) agent stage
            await emitter.emit(
                "captured",
                f"Captured page: {distilled.token_estimate} skeleton tokens, "
                f"{len(result.xhr)} hidden JSON response(s), "
                f"{len(distilled.structures)} structure(s)",
                data={
                    "tokens": distilled.token_estimate,
                    "xhr_count": len(result.xhr),
                    "structures": len(distilled.structures),
                },
            )
            log.info(
                "job_captured",
                job_id=job_id,
                tokens=distilled.token_estimate,
                xhr=len(result.xhr),
                structures=len(distilled.structures),
            )

            run_agent = ctx.get("run_agent")
            if run_agent is None and settings.llm_configured:
                run_agent = run_agent_default
            if run_agent is None:
                # No LLM configured: analysis stops at the captured snapshot.
                _set_status(job, JobStatus.DONE, reason="captured page (no LLM configured)")
                await session.commit()
                await emitter.emit(
                    "captured_only", "No LLM configured — stopping at the page snapshot"
                )
                return "captured"

            context = build_context(url, result, distilled)
            slug = make_slug(url)
            outcome = await _run_agent_stage(
                run_agent, ctx, settings, job_id, context, slug, emitter
            )
            if outcome.ok:
                _set_status(
                    job,
                    JobStatus.DONE,
                    reason=(
                        f"built extractor '{slug}' via {outcome.strategy} "
                        f"after {outcome.repair_count} repair(s)"
                    ),
                )
                await session.commit()
                await emitter.emit(
                    "live",
                    f"Your API is live at /api/{slug}",
                    data={
                        "slug": slug,
                        "endpoint": f"/api/{slug}",
                        "docs": f"/api/{slug}/docs",
                        "record_count": len(outcome.records or []),
                        "strategy": outcome.strategy,
                        "repairs": outcome.repair_count,
                    },
                )
                log.info("job_done", job_id=job_id, slug=slug, strategy=outcome.strategy)
                return "done"

            _set_status(
                job,
                JobStatus.FAILED,
                reason=f"could not build a validated extractor: {outcome.reason}",
            )
            await session.commit()
            log.info("job_no_extractor", job_id=job_id, reason=outcome.reason)
            return "no_extractor"
        except Exception as exc:  # noqa: BLE001 — job must record any failure
            log.exception("job_failed", job_id=job_id)
            _set_status(job, JobStatus.FAILED, reason=str(exc))
            await session.commit()
            await emitter.emit("failed", f"Something broke: {exc}", data={"stage": "crash"})
            return "failed"


def _ensure_aware(dt):
    """SQLite returns naive datetimes for tz-aware columns; normalise to UTC."""
    from datetime import UTC

    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _is_due(extractor: Extractor, now) -> bool:
    last = _ensure_aware(extractor.last_refreshed_at)
    if last is None:
        return True
    from datetime import timedelta

    return now - last >= timedelta(minutes=extractor.refresh_interval_minutes)


def _match_xhr(xhr: list[dict], target: str) -> str | None:
    """Find the stored hidden-API response in a fresh capture.

    Exact URL first; then host+path (query strings often carry timestamps/keys)."""
    for r in xhr:
        if r.get("url") == target:
            return r.get("body", "")
    want = urlsplit(target)
    for r in xhr:
        got = urlsplit(r.get("url", ""))
        if (got.hostname, got.path) == (want.hostname, want.path):
            return r.get("body", "")
    return None


async def schedule_refreshes(ctx: dict) -> int:
    """Cron entrypoint: enqueue a refresh for every active extractor that is due.

    Bounded by max_active_extractors (20), so loading actives and filtering in
    Python is simpler and DB-portable versus datetime arithmetic in SQL."""
    sessionmaker = ctx["sessionmaker"]
    now = utcnow()
    async with sessionmaker() as session:
        actives = (
            (await session.execute(sa.select(Extractor).where(Extractor.status == "active")))
            .scalars()
            .all()
        )
    due = [e for e in actives if _is_due(e, now)]
    for extractor in due:
        await ctx["redis"].enqueue_job("refresh_extractor", str(extractor.id))
    if due:
        log.info("refreshes_scheduled", count=len(due))
    return len(due)


async def refresh_extractor(ctx: dict, extractor_id: str) -> str:
    """Re-scrape one extractor's source and swap in the fresh data.

    Stale-while-revalidate: the cached data is only replaced on success. Any
    failure increments a strike counter; the third consecutive strike pauses
    the extractor with the reason stored (a paused endpoint still serves its
    last good data, clearly marked)."""
    settings: Settings = ctx["settings"]
    sessionmaker = ctx["sessionmaker"]
    robots_check = ctx.get("robots_check", check_robots)
    capture = ctx.get("capture", capture_page)
    resolve = ctx.get("resolve", default_resolver)
    sandbox = ctx.get("sandbox") or (
        lambda code, source, timeout: run_extractor(
            code, source, timeout=timeout, memory_mb=settings.sandbox_memory_mb
        )
    )

    async with sessionmaker() as session:
        extractor = await session.get(Extractor, uuid.UUID(extractor_id))
        if extractor is None:
            return "missing"
        if extractor.status != "active":
            return "skipped"

        try:
            url = validate_target_url(
                extractor.source_url, resolve=resolve, deny_hosts=settings.deny_hosts_set
            )
            host = urlsplit(url).hostname or ""

            await _respect_domain_rate(ctx.get("redis"), host)
            verdict = await robots_check(
                url, user_agent=settings.user_agent, client=ctx.get("http")
            )
            if not verdict.allowed:
                raise RefreshFailed(f"robots.txt no longer allows this page: {verdict.reason}")

            await _respect_domain_rate(ctx.get("redis"), host)
            result = await capture(url, settings)

            if extractor.strategy == "json_xhr":
                source = _match_xhr(result.xhr, extractor.target or "")
                if source is None:
                    raise RefreshFailed(
                        f"hidden API {extractor.target!r} was not observed on the page anymore"
                    )
            else:
                source = result.final_html

            sandbox_result = await asyncio.to_thread(
                sandbox, extractor.code, source, settings.sandbox_timeout_s
            )
            if not sandbox_result.ok:
                raise RefreshFailed(sandbox_result.error or "extractor errored")

            report = validate_records(sandbox_result.records, extractor.record_schema or {})
            if not report.ok:
                raise RefreshFailed(report.reason)
        except RefreshFailed as exc:
            return await _record_refresh_failure(session, extractor, str(exc))
        except Exception as exc:  # noqa: BLE001 — a crash is a refresh failure too
            return await _record_refresh_failure(session, extractor, str(exc))

        extractor.data = sandbox_result.records
        extractor.sample = sandbox_result.records[:5]
        extractor.last_refreshed_at = utcnow()
        extractor.consecutive_failures = 0
        await session.commit()
        log.info("extractor_refreshed", slug=extractor.slug, records=len(extractor.data))
        return "refreshed"


class RefreshFailed(Exception):
    pass


async def _record_refresh_failure(session, extractor: Extractor, reason: str) -> str:
    extractor.consecutive_failures += 1
    if extractor.consecutive_failures >= 3:
        extractor.status = "paused"
        extractor.paused_reason = f"paused after 3 consecutive refresh failures: {reason}"
        await session.commit()
        log.warning("extractor_paused", slug=extractor.slug, reason=reason)
        return "paused"
    await session.commit()
    log.info(
        "extractor_refresh_failed",
        slug=extractor.slug,
        failures=extractor.consecutive_failures,
        reason=reason,
    )
    return "failed"


async def startup(ctx: dict) -> None:
    configure_logging()
    settings = Settings()
    ctx["settings"] = settings
    engine = make_engine(settings.database_url)
    ctx["engine"] = engine
    ctx["sessionmaker"] = make_sessionmaker(engine)
    ctx["http"] = httpx.AsyncClient(
        timeout=8, follow_redirects=True, headers={"User-Agent": settings.user_agent}
    )


async def shutdown(ctx: dict) -> None:
    await ctx["http"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [analyze_job, refresh_extractor]
    # Scan for due extractors every 5 minutes; each due one becomes its own job
    # so max_jobs bounds concurrent Chromium instances during refreshes too.
    cron_jobs = [cron(schedule_refreshes, minute=set(range(0, 60, 5)))]
    on_startup = startup
    on_shutdown = shutdown
    # Playwright is the memory hog: at most 2 concurrent captures on the 4GB box.
    max_jobs = 2
    job_timeout = 120
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
