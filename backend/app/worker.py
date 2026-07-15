"""arq worker: the analyze_job pipeline (validate -> robots -> capture -> distill -> persist).

External stages (DNS, robots fetch, browser capture) are read from ctx with real
defaults, so tests inject fakes by overriding ctx keys.
"""

import asyncio
import uuid
from urllib.parse import urlsplit

import httpx
import structlog
from arq.connections import RedisSettings

from app.agent.service import build_context, make_slug
from app.agent.service import run_agent as run_agent_default
from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.events import EventEmitter
from app.ingestion.capture import capture_page
from app.ingestion.distill import distill
from app.ingestion.robots import check_robots
from app.ingestion.urlguard import default_resolver, validate_target_url
from app.job_states import JobStatus, assert_transition
from app.logging import configure_logging
from app.models import Extractor, Job, LLMCall, PageSnapshot

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


async def _run_agent_stage(run_agent, ctx, settings, job_id: str, context: dict, slug: str):
    """Run the agent, streaming events, then persist its LLM calls and (if any) extractor."""
    sessionmaker = ctx["sessionmaker"]
    emitter = EventEmitter(job_id, sessionmaker, ctx.get("redis"))
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
            session.add(
                Extractor(
                    job_id=job_uuid,
                    slug=slug,
                    source_url=context["url"],
                    strategy=outcome.strategy,
                    code=outcome.code or "",
                    record_schema=outcome.record_schema or {},
                    sample=(outcome.records or [])[:5],
                )
            )
        await session.commit()
    return outcome


async def analyze_job(ctx: dict, job_id: str) -> str:
    settings: Settings = ctx["settings"]
    sessionmaker = ctx["sessionmaker"]
    robots_check = ctx.get("robots_check", check_robots)
    capture = ctx.get("capture", capture_page)
    resolve = ctx.get("resolve", default_resolver)
    http: httpx.AsyncClient | None = ctx.get("http")

    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if job is None:
            log.warning("job_missing", job_id=job_id)
            return "missing"

        _set_status(job, JobStatus.ANALYZING)
        await session.commit()
        log.info("job_analyzing", job_id=job_id, url=job.url)

        try:
            url = validate_target_url(job.url, resolve=resolve)
            host = urlsplit(url).hostname or ""

            await _respect_domain_rate(ctx.get("redis"), host)
            verdict = await robots_check(url, user_agent=settings.user_agent, client=http)
            if not verdict.allowed:
                _set_status(job, JobStatus.FAILED, reason=verdict.reason)
                await session.commit()
                log.info("job_blocked_by_robots", job_id=job_id, reason=verdict.reason)
                return "blocked"

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
                return "captured"

            context = build_context(url, result, distilled)
            slug = make_slug(url)
            outcome = await _run_agent_stage(run_agent, ctx, settings, job_id, context, slug)
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
    functions = [analyze_job]
    on_startup = startup
    on_shutdown = shutdown
    # Playwright is the memory hog: at most 2 concurrent captures on the 4GB box.
    max_jobs = 2
    job_timeout = 120
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
