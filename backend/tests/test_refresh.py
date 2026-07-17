"""Tests for the scheduled refresh pipeline: due-selection, stale-while-revalidate
updates, 3-strike auto-pause, and json_xhr re-matching."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ingestion.capture import CaptureResult
from app.ingestion.robots import RobotsVerdict
from app.models import Extractor
from app.sandbox import SandboxResult
from app.worker import refresh_extractor, schedule_refreshes

ALLOWED = RobotsVerdict(allowed=True, status="allowed", reason="ok")

SCHEMA = {"fields": [{"name": "title", "type": "string", "required": True}]}


def utc(**delta) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


async def make_extractor(sessionmaker, **overrides) -> Extractor:
    values = dict(
        slug="site-test",
        source_url="https://site.test/page",
        strategy="html",
        code="def extract(html):\n    return [{'title': 'x'}]",
        record_schema=SCHEMA,
        data=[{"title": "stale"}],
        status="active",
        refresh_interval_minutes=30,
        last_refreshed_at=utc(minutes=45),
    )
    values.update(overrides)
    async with sessionmaker() as session:
        ext = Extractor(**values)
        session.add(ext)
        await session.commit()
        return ext


class FakeArq:
    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.enqueued.append((name, args))

    async def set(self, *a, **kw):  # domain rate lock
        return True


async def fake_capture(url, settings):
    return CaptureResult(final_url=url, final_html="<h1>fresh</h1>", xhr=[])


@pytest.fixture
def ctx(settings, sessionmaker):
    async def robots_ok(url, user_agent, client):
        return ALLOWED

    def fake_sandbox(code, source, timeout=10):
        return SandboxResult(ok=True, records=[{"title": "fresh"}], error=None)

    return {
        "settings": settings,
        "sessionmaker": sessionmaker,
        "http": None,
        "redis": FakeArq(),
        "robots_check": robots_ok,
        "capture": fake_capture,
        "resolve": lambda host: ["93.184.216.34"],
        "sandbox": fake_sandbox,
    }


async def reload(sessionmaker, ext_id) -> Extractor:
    async with sessionmaker() as session:
        return await session.get(Extractor, ext_id)


class TestScheduling:
    async def test_due_extractors_are_enqueued(self, ctx, sessionmaker):
        due = await make_extractor(sessionmaker, last_refreshed_at=utc(minutes=45))
        fresh = await make_extractor(
            sessionmaker, slug="fresh-site", last_refreshed_at=utc(minutes=5)
        )
        never = await make_extractor(
            sessionmaker, slug="never-refreshed", last_refreshed_at=None
        )
        count = await schedule_refreshes(ctx)
        enqueued_ids = {args[0] for name, args in ctx["redis"].enqueued}
        assert count == 2
        assert str(due.id) in enqueued_ids
        assert str(never.id) in enqueued_ids
        assert str(fresh.id) not in enqueued_ids

    async def test_paused_and_evicted_are_never_scheduled(self, ctx, sessionmaker):
        await make_extractor(sessionmaker, status="paused")
        await make_extractor(sessionmaker, slug="gone", status="evicted")
        assert await schedule_refreshes(ctx) == 0

    async def test_per_extractor_interval_is_respected(self, ctx, sessionmaker):
        await make_extractor(
            sessionmaker, refresh_interval_minutes=120, last_refreshed_at=utc(minutes=45)
        )
        assert await schedule_refreshes(ctx) == 0


class TestRefresh:
    async def test_success_updates_data_and_resets_failures(self, ctx, sessionmaker):
        ext = await make_extractor(sessionmaker, consecutive_failures=2)
        before = ext.last_refreshed_at
        outcome = await refresh_extractor(ctx, str(ext.id))
        assert outcome == "refreshed"
        ext = await reload(sessionmaker, ext.id)
        assert ext.data == [{"title": "fresh"}]
        assert ext.consecutive_failures == 0
        assert ext.last_refreshed_at.replace(tzinfo=UTC) > before

    async def test_failure_increments_counter(self, ctx, sessionmaker):
        def broken_sandbox(code, source, timeout=10):
            return SandboxResult(ok=False, records=None, error="selectors broke")

        ctx["sandbox"] = broken_sandbox
        ext = await make_extractor(sessionmaker)
        outcome = await refresh_extractor(ctx, str(ext.id))
        assert outcome == "failed"
        ext = await reload(sessionmaker, ext.id)
        assert ext.consecutive_failures == 1
        assert ext.status == "active"
        assert ext.data == [{"title": "stale"}]  # stale data survives

    async def test_third_failure_pauses_with_reason(self, ctx, sessionmaker):
        def broken_sandbox(code, source, timeout=10):
            return SandboxResult(ok=False, records=None, error="selectors broke")

        ctx["sandbox"] = broken_sandbox
        ext = await make_extractor(sessionmaker, consecutive_failures=2)
        outcome = await refresh_extractor(ctx, str(ext.id))
        assert outcome == "paused"
        ext = await reload(sessionmaker, ext.id)
        assert ext.status == "paused"
        assert "selectors broke" in ext.paused_reason
        assert ext.consecutive_failures == 3

    async def test_validation_failure_counts_as_failure(self, ctx, sessionmaker):
        def wrong_shape_sandbox(code, source, timeout=10):
            return SandboxResult(ok=True, records=[{"title": 123}], error=None)

        ctx["sandbox"] = wrong_shape_sandbox
        ext = await make_extractor(sessionmaker)
        assert await refresh_extractor(ctx, str(ext.id)) == "failed"
        ext = await reload(sessionmaker, ext.id)
        assert ext.consecutive_failures == 1

    async def test_inactive_extractor_is_skipped(self, ctx, sessionmaker):
        ext = await make_extractor(sessionmaker, status="paused")
        assert await refresh_extractor(ctx, str(ext.id)) == "skipped"


class TestJsonXhrRefresh:
    async def make_xhr_extractor(self, sessionmaker, target):
        return await make_extractor(
            sessionmaker,
            strategy="json_xhr",
            target=target,
            code="import json\ndef extract(body):\n    return json.loads(body)",
        )

    async def test_matches_stored_xhr_url_exactly(self, ctx, sessionmaker):
        seen = {}

        async def capture_with_xhr(url, settings):
            return CaptureResult(
                final_url=url,
                final_html="<html></html>",
                xhr=[{"url": "https://site.test/api/items?page=1", "body": '[{"title": "x"}]'}],
            )

        def spy_sandbox(code, source, timeout=10):
            seen["source"] = source
            return SandboxResult(ok=True, records=[{"title": "x"}], error=None)

        ctx["capture"] = capture_with_xhr
        ctx["sandbox"] = spy_sandbox
        ext = await self.make_xhr_extractor(
            sessionmaker, "https://site.test/api/items?page=1"
        )
        assert await refresh_extractor(ctx, str(ext.id)) == "refreshed"
        assert seen["source"] == '[{"title": "x"}]'

    async def test_falls_back_to_host_and_path_match(self, ctx, sessionmaker):
        async def capture_with_xhr(url, settings):
            return CaptureResult(
                final_url=url,
                final_html="<html></html>",
                xhr=[{"url": "https://site.test/api/items?ts=999", "body": '[{"title": "x"}]'}],
            )

        ctx["capture"] = capture_with_xhr
        ext = await self.make_xhr_extractor(
            sessionmaker, "https://site.test/api/items?ts=111"
        )
        assert await refresh_extractor(ctx, str(ext.id)) == "refreshed"

    async def test_missing_hidden_api_is_a_failure(self, ctx, sessionmaker):
        ext = await self.make_xhr_extractor(
            sessionmaker, "https://site.test/api/items"
        )  # fake_capture returns no xhr
        assert await refresh_extractor(ctx, str(ext.id)) == "failed"
        ext = await reload(sessionmaker, ext.id)
        assert ext.consecutive_failures == 1


class TestOutcomeTarget:
    async def test_worker_persists_json_xhr_target(self, sessionmaker, settings):
        # covered via worker wiring: AgentOutcome.target lands on the Extractor row
        from app.agent.loop import AgentOutcome
        from app.worker import analyze_job
        from tests.test_worker import fake_capture as page_capture

        async def robots_ok(url, user_agent, client):
            return ALLOWED

        async def fake_agent(*, context, settings, http, emitter, on_call, sandbox):
            return AgentOutcome(
                ok=True, strategy="json_xhr", target="https://site.test/api/items",
                records=[{"title": "A"}], code="def extract(b):\n    return []",
                record_schema=SCHEMA, reason="validated",
            )

        ctx = {
            "settings": settings, "sessionmaker": sessionmaker, "http": None,
            "robots_check": robots_ok, "capture": page_capture,
            "resolve": lambda host: ["93.184.216.34"], "run_agent": fake_agent,
        }
        from tests.test_worker import make_job

        job_id = await make_job(sessionmaker)
        await analyze_job(ctx, job_id)
        async with sessionmaker() as session:
            ext = (await session.execute(select(Extractor))).scalar_one()
        assert ext.target == "https://site.test/api/items"
