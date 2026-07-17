"""Tests for abuse protection: responsible-use token, job rate limits, LRU cap."""

import pytest
from sqlalchemy import select

from app.agent.loop import AgentOutcome
from app.models import Extractor
from app.ratelimit import JobRateLimiter
from app.worker import analyze_job


class FakeRedis:
    """Just enough of redis for the fixed-window limiter: INCR + EXPIRE."""

    def __init__(self):
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        self.expires[key] = seconds


class TestResponsibleUse:
    async def test_job_without_responsible_use_is_rejected(self, api, app):
        resp = await api.post("/jobs", json={"url": "https://example.com/x"})
        assert resp.status_code == 422
        assert app.state.queue.enqueued == []

    async def test_job_with_responsible_use_false_is_rejected(self, api, app):
        resp = await api.post(
            "/jobs", json={"url": "https://example.com/x", "responsible_use": False}
        )
        assert resp.status_code == 422

    async def test_job_with_responsible_use_true_is_accepted(self, api):
        resp = await api.post(
            "/jobs", json={"url": "https://example.com/x", "responsible_use": True}
        )
        assert resp.status_code == 202


class TestJobRateLimiter:
    async def test_allows_up_to_per_ip_limit(self):
        limiter = JobRateLimiter(FakeRedis(), per_ip=3, global_limit=100)
        for _ in range(3):
            assert await limiter.check("1.2.3.4") is None

    async def test_denies_fourth_job_from_same_ip(self):
        limiter = JobRateLimiter(FakeRedis(), per_ip=3, global_limit=100)
        for _ in range(3):
            await limiter.check("1.2.3.4")
        reason = await limiter.check("1.2.3.4")
        assert reason is not None and "hour" in reason

    async def test_different_ips_have_separate_budgets(self):
        limiter = JobRateLimiter(FakeRedis(), per_ip=1, global_limit=100)
        assert await limiter.check("1.1.1.1") is None
        assert await limiter.check("2.2.2.2") is None

    async def test_global_limit_caps_everyone(self):
        limiter = JobRateLimiter(FakeRedis(), per_ip=100, global_limit=2)
        assert await limiter.check("1.1.1.1") is None
        assert await limiter.check("2.2.2.2") is None
        assert await limiter.check("3.3.3.3") is not None

    async def test_counters_get_an_expiry(self):
        redis = FakeRedis()
        limiter = JobRateLimiter(redis, per_ip=3, global_limit=100, window_s=3600)
        await limiter.check("1.2.3.4")
        assert set(redis.expires.values()) == {3600}


class TestRateLimitedEndpoint:
    async def test_429_when_ip_budget_exhausted(self, api, app):
        app.state.limiter = JobRateLimiter(FakeRedis(), per_ip=1, global_limit=100)
        payload = {"url": "https://example.com/x", "responsible_use": True}
        assert (await api.post("/jobs", json=payload)).status_code == 202
        resp = await api.post("/jobs", json=payload)
        assert resp.status_code == 429
        assert "hour" in resp.json()["detail"]


def _fake_agent(records=None):
    async def fake(*, context, settings, http, emitter, on_call, sandbox):
        return AgentOutcome(
            ok=True, strategy="html", records=records or [{"title": "A"}],
            code="def extract(html):\n    return []",
            record_schema={"fields": []}, reason="validated",
        )

    return fake


@pytest.fixture
def worker_ctx(settings, sessionmaker):
    from app.ingestion.robots import RobotsVerdict
    from tests.test_worker import fake_capture

    async def robots_ok(url, user_agent, client):
        return RobotsVerdict(allowed=True, status="allowed", reason="ok")

    return {
        "settings": settings,
        "sessionmaker": sessionmaker,
        "http": None,
        "robots_check": robots_ok,
        "capture": fake_capture,
        "resolve": lambda host: ["93.184.216.34"],
        "run_agent": _fake_agent(),
    }


async def _run_job(worker_ctx, sessionmaker, url):
    from tests.test_worker import make_job

    job_id = await make_job(sessionmaker, url=url)
    await analyze_job(worker_ctx, job_id)


async def _all_extractors(sessionmaker):
    async with sessionmaker() as session:
        return (
            (await session.execute(select(Extractor).order_by(Extractor.created_at)))
            .scalars().all()
        )


class TestActiveCap:
    async def test_lru_eviction_beyond_max_active(self, worker_ctx, sessionmaker, settings):
        settings.max_active_extractors = 2
        for host in ("one.test", "two.test", "three.test"):
            await _run_job(worker_ctx, sessionmaker, f"https://{host}/page")

        extractors = await _all_extractors(sessionmaker)
        by_slug = {e.slug: e for e in extractors}
        assert by_slug["one-test-page"].status == "evicted"
        assert "least recently" in by_slug["one-test-page"].paused_reason
        assert by_slug["two-test-page"].status == "active"
        assert by_slug["three-test-page"].status == "active"

    async def test_new_version_supersedes_old_not_evicts_others(
        self, worker_ctx, sessionmaker, settings
    ):
        settings.max_active_extractors = 2
        await _run_job(worker_ctx, sessionmaker, "https://one.test/page")
        await _run_job(worker_ctx, sessionmaker, "https://two.test/page")
        await _run_job(worker_ctx, sessionmaker, "https://one.test/page")  # re-run

        extractors = await _all_extractors(sessionmaker)
        one = sorted(
            (e for e in extractors if e.slug == "one-test-page"), key=lambda e: e.version
        )
        assert [e.status for e in one] == ["superseded", "active"]
        two = next(e for e in extractors if e.slug == "two-test-page")
        assert two.status == "active"  # replacing a version must not evict anyone
