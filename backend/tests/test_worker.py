"""Tests for the analyze_job pipeline with injected fakes for browser/network stages."""

import uuid

import pytest
from sqlalchemy import select

from app.ingestion.capture import CaptureResult
from app.ingestion.robots import RobotsVerdict
from app.job_states import JobStatus
from app.models import Job, PageSnapshot
from app.worker import analyze_job

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
