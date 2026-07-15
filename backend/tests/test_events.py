"""Tests for the agent event stream: sequencing, persistence, and Redis pub/sub fan-out."""

import json
import uuid

from sqlalchemy import select

from app.events import AgentEvent, EventEmitter, event_channel
from app.job_states import JobStatus
from app.models import Job, JobEvent


class FakeRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


async def make_job(sessionmaker) -> str:
    async with sessionmaker() as session:
        job = Job(url="https://site.test/page", status=JobStatus.ANALYZING.value)
        session.add(job)
        await session.commit()
        return str(job.id)


async def test_emitted_event_is_persisted_with_incrementing_seq(sessionmaker):
    job_id = await make_job(sessionmaker)
    redis = FakeRedis()
    emitter = EventEmitter(job_id=job_id, sessionmaker=sessionmaker, redis=redis)

    await emitter.emit("strategy_chosen", "Using hidden JSON API", data={"strategy": "json_xhr"})
    await emitter.emit("code_generated", "Wrote extract()")

    async with sessionmaker() as session:
        stmt = (
            select(JobEvent)
            .where(JobEvent.job_id == uuid.UUID(job_id))
            .order_by(JobEvent.seq)
        )
        rows = (await session.execute(stmt)).scalars().all()
    assert [r.seq for r in rows] == [1, 2]
    assert rows[0].kind == "strategy_chosen"
    assert rows[0].message == "Using hidden JSON API"
    assert rows[0].data == {"strategy": "json_xhr"}


async def test_emitted_event_is_published_to_job_channel(sessionmaker):
    job_id = await make_job(sessionmaker)
    redis = FakeRedis()
    emitter = EventEmitter(job_id=job_id, sessionmaker=sessionmaker, redis=redis)

    await emitter.emit("validated", "3 records extracted", data={"count": 3})

    assert len(redis.published) == 1
    channel, raw = redis.published[0]
    assert channel == event_channel(job_id)
    payload = json.loads(raw)
    assert payload["kind"] == "validated"
    assert payload["seq"] == 1
    assert payload["data"] == {"count": 3}


async def test_works_without_redis(sessionmaker):
    job_id = await make_job(sessionmaker)
    emitter = EventEmitter(job_id=job_id, sessionmaker=sessionmaker, redis=None)
    await emitter.emit("test_failed", "schema mismatch")  # must not raise
    async with sessionmaker() as session:
        rows = (await session.execute(select(JobEvent))).scalars().all()
    assert len(rows) == 1


def test_agent_event_serializes_roundtrip():
    ev = AgentEvent(seq=5, kind="repair_attempt", message="retry 2/4", data={"iteration": 2})
    restored = AgentEvent.from_json(ev.to_json())
    assert restored.seq == 5
    assert restored.kind == "repair_attempt"
    assert restored.data == {"iteration": 2}
