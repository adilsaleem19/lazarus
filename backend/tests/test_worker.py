"""Tests for the analyze_job pipeline with injected fakes for browser/network stages."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.loop import AgentOutcome
from app.ingestion.capture import CaptureResult
from app.ingestion.robots import RobotsVerdict
from app.job_states import JobStatus
from app.models import Extractor, Job, JobEvent, LLMCall, PageSnapshot
from app.worker import analyze_job

FAKE_CALL = {
    "provider": "groq",
    "model": "llama-4-scout",
    "purpose": "codegen",
    "prompt": "generate an extractor",
    "response": '{"code": "..."}',
    "prompt_tokens": 40,
    "completion_tokens": 12,
    "total_tokens": 52,
}

CARDS_HTML = (
    "<html><head><title>Shop</title></head><body><div id='grid'>"
    + "".join(f"<div class='card'><h3>P{i}</h3><a href='/p/{i}'>go</a></div>" for i in range(6))
    + "</div></body></html>"
)

ALLOWED = RobotsVerdict(allowed=True, status="allowed", reason="no matching disallow rule")
BLOCKED = RobotsVerdict(allowed=False, status="disallowed", reason="robots.txt disallows /page")


async def fake_capture(url, settings):
    return CaptureResult(
        final_url=url,
        final_html=CARDS_HTML,
        xhr=[{"url": url + "/api/items", "method": "GET", "status": 200, "body": "[]"}],
    )


async def make_job(sessionmaker, url="https://site.test/page") -> str:
    async with sessionmaker() as session:
        job = Job(url=url, status=JobStatus.QUEUED.value)
        session.add(job)
        await session.commit()
        return str(job.id)


async def reload_job(sessionmaker, job_id):
    async with sessionmaker() as session:
        job = (
            await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        ).scalar_one()
        snap = (
            await session.execute(select(PageSnapshot).where(PageSnapshot.job_id == job.id))
        ).scalar_one_or_none()
        return job, snap


@pytest.fixture
def ctx(settings, sessionmaker):
    async def robots_ok(url, user_agent, client):
        return ALLOWED

    return {
        "settings": settings,
        "sessionmaker": sessionmaker,
        "http": None,  # robots fake ignores it
        "robots_check": robots_ok,
        "capture": fake_capture,
        "resolve": lambda host: ["93.184.216.34"],
    }


async def test_happy_path_persists_snapshot_and_marks_done(ctx, sessionmaker):
    job_id = await make_job(sessionmaker)
    await analyze_job(ctx, job_id)
    job, snap = await reload_job(sessionmaker, job_id)
    assert job.status == JobStatus.DONE.value
    assert snap is not None
    assert snap.token_estimate > 0
    assert snap.robots_status == "allowed"
    assert snap.xhr[0]["status"] == 200
    assert any(s["type"] == "repeated_pattern" for s in snap.structures)
    assert snap.meta["title"] == "Shop"


async def test_robots_disallow_fails_job_with_reason(ctx, sessionmaker):
    async def robots_no(url, user_agent, client):
        return BLOCKED

    ctx["robots_check"] = robots_no
    job_id = await make_job(sessionmaker)
    await analyze_job(ctx, job_id)
    job, snap = await reload_job(sessionmaker, job_id)
    assert job.status == JobStatus.FAILED.value
    assert "robots.txt" in job.reason
    assert snap is None


async def test_capture_crash_fails_job(ctx, sessionmaker):
    async def broken_capture(url, settings):
        raise RuntimeError("browser crashed")

    ctx["capture"] = broken_capture
    job_id = await make_job(sessionmaker)
    await analyze_job(ctx, job_id)
    job, _ = await reload_job(sessionmaker, job_id)
    assert job.status == JobStatus.FAILED.value
    assert "browser crashed" in job.reason


async def test_url_resolving_to_private_ip_fails_job(ctx, sessionmaker):
    ctx["resolve"] = lambda host: ["10.0.0.7"]
    job_id = await make_job(sessionmaker)
    await analyze_job(ctx, job_id)
    job, _ = await reload_job(sessionmaker, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.reason


async def _rows(sessionmaker, model, job_id):
    async with sessionmaker() as session:
        result = await session.execute(select(model).where(model.job_id == uuid.UUID(job_id)))
        return result.scalars().all()


async def test_agent_success_persists_extractor_calls_and_events(ctx, sessionmaker):
    async def fake_agent(*, context, settings, http, emitter, on_call, sandbox):
        await emitter.emit("strategy_chosen", "Parsing the HTML", data={"strategy": "html"})
        on_call(dict(FAKE_CALL))
        return AgentOutcome(
            ok=True,
            strategy="html",
            records=[{"title": "P0", "url": "/p/0"}, {"title": "P1", "url": "/p/1"}],
            code="def extract(html):\n    return []",
            record_schema={"fields": [{"name": "title", "type": "string", "required": True}]},
            repair_count=1,
            reason="validated",
        )

    ctx["run_agent"] = fake_agent
    job_id = await make_job(sessionmaker, url="https://books.toscrape.com/catalogue/page-1.html")
    outcome = await analyze_job(ctx, job_id)
    assert outcome == "done"

    job, snap = await reload_job(sessionmaker, job_id)
    assert job.status == JobStatus.DONE.value
    assert snap is not None

    extractors = await _rows(sessionmaker, Extractor, job_id)
    assert len(extractors) == 1
    ext = extractors[0]
    assert ext.strategy == "html"
    assert ext.slug == "books-toscrape-com-catalogue"
    assert ext.source_url == "https://books.toscrape.com/catalogue/page-1.html"
    assert ext.sample == [{"title": "P0", "url": "/p/0"}, {"title": "P1", "url": "/p/1"}]

    calls = await _rows(sessionmaker, LLMCall, job_id)
    assert len(calls) == 1
    assert calls[0].total_tokens == 52

    events = await _rows(sessionmaker, JobEvent, job_id)
    assert any(e.kind == "strategy_chosen" for e in events)


async def test_agent_success_stores_full_data_and_refresh_metadata(ctx, sessionmaker):
    records = [{"title": f"P{i}", "url": f"/p/{i}"} for i in range(12)]

    async def fake_agent(*, context, settings, http, emitter, on_call, sandbox):
        return AgentOutcome(ok=True, strategy="html", records=records,
                            code="def extract(html):\n    return []",
                            record_schema={"fields": []}, reason="validated")

    ctx["run_agent"] = fake_agent
    job_id = await make_job(sessionmaker)
    await analyze_job(ctx, job_id)

    ext = (await _rows(sessionmaker, Extractor, job_id))[0]
    assert ext.data == records  # the FULL result set, not just the sample
    assert ext.sample == records[:5]
    assert ext.status == "active"
    assert ext.last_refreshed_at is not None
    assert ext.refresh_interval_minutes == 30
    assert ext.consecutive_failures == 0


async def test_second_run_for_same_slug_bumps_version(ctx, sessionmaker):
    async def fake_agent(*, context, settings, http, emitter, on_call, sandbox):
        return AgentOutcome(ok=True, strategy="html", records=[{"title": "A"}],
                            code="def extract(html):\n    return []",
                            record_schema={"fields": []}, reason="validated")

    ctx["run_agent"] = fake_agent
    url = "https://site.test/page"
    for _ in range(2):
        job_id = await make_job(sessionmaker, url=url)
        await analyze_job(ctx, job_id)

    async with sessionmaker() as session:
        rows = (
            (await session.execute(select(Extractor).order_by(Extractor.version)))
            .scalars().all()
        )
    assert [r.version for r in rows] == [1, 2]
    assert rows[0].slug == rows[1].slug


async def test_agent_failure_marks_failed_but_keeps_snapshot(ctx, sessionmaker):
    async def fake_agent(*, context, settings, http, emitter, on_call, sandbox):
        on_call(dict(FAKE_CALL))
        return AgentOutcome(
            ok=False, strategy="html", repair_count=4, reason="exhausted repair attempts"
        )

    ctx["run_agent"] = fake_agent
    job_id = await make_job(sessionmaker)
    outcome = await analyze_job(ctx, job_id)
    assert outcome == "no_extractor"

    job, snap = await reload_job(sessionmaker, job_id)
    assert job.status == JobStatus.FAILED.value
    assert "exhausted repair attempts" in job.reason
    assert snap is not None  # the captured snapshot survives the agent failure

    assert await _rows(sessionmaker, Extractor, job_id) == []
    # even a failed run logs its LLM spend for cost tracking
    assert len(await _rows(sessionmaker, LLMCall, job_id)) == 1
