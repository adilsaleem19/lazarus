"""Tests for the live event stream: DB replay, live pub/sub follow, terminal close."""

import json

from app.events import AgentEvent, EventEmitter, event_channel
from app.models import Job
from app.sse import stream_job_events


class FakePubSub:
    def __init__(self, scripted: list[str]):
        self.scripted = list(scripted)
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        if self.scripted:
            return {"type": "message", "data": self.scripted.pop(0)}
        return None

    async def unsubscribe(self, channel):
        pass

    async def aclose(self):
        self.closed = True


class FakeRedis:
    def __init__(self, scripted: list[str]):
        self._pubsub = FakePubSub(scripted)

    def pubsub(self):
        return self._pubsub


async def make_job_with_events(sessionmaker, kinds: list[str]) -> str:
    async with sessionmaker() as session:
        job = Job(url="https://site.test/", status="analyzing")
        session.add(job)
        await session.commit()
        job_id = str(job.id)
    emitter = EventEmitter(job_id, sessionmaker)
    for kind in kinds:
        await emitter.emit(kind, f"msg {kind}")
    return job_id


def parse_stream(chunks: list[str]) -> list[dict]:
    return [
        json.loads(c.removeprefix("data: ").strip())
        for c in chunks
        if c.startswith("data: ")
    ]


async def collect(gen, limit=50) -> list[str]:
    out = []
    async for chunk in gen:
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


async def test_replays_persisted_events_in_order(sessionmaker):
    job_id = await make_job_with_events(sessionmaker, ["analyzing", "captured"])
    chunks = await collect(
        stream_job_events(sessionmaker, None, job_id, max_seconds=0.1)
    )
    events = parse_stream(chunks)
    assert [e["kind"] for e in events] == ["analyzing", "captured"]
    assert [e["seq"] for e in events] == [1, 2]


async def test_stream_closes_after_terminal_replay_event(sessionmaker):
    job_id = await make_job_with_events(sessionmaker, ["analyzing", "live"])
    redis = FakeRedis(scripted=[AgentEvent(seq=3, kind="ghost", message="x").to_json()])
    chunks = await collect(stream_job_events(sessionmaker, redis, job_id))
    events = parse_stream(chunks)
    assert events[-1]["kind"] == "live"
    assert redis._pubsub.subscribed == []  # never went live: replay already terminal


async def test_follows_live_events_until_terminal(sessionmaker):
    job_id = await make_job_with_events(sessionmaker, ["analyzing"])
    live = [
        AgentEvent(seq=2, kind="strategy_chosen", message="html").to_json(),
        AgentEvent(seq=3, kind="live", message="done", data={"slug": "s"}).to_json(),
        AgentEvent(seq=4, kind="after", message="never seen").to_json(),
    ]
    redis = FakeRedis(scripted=live)
    chunks = await collect(stream_job_events(sessionmaker, redis, job_id, max_seconds=5))
    events = parse_stream(chunks)
    assert [e["kind"] for e in events] == ["analyzing", "strategy_chosen", "live"]
    assert redis._pubsub.subscribed == [event_channel(job_id)]
    assert redis._pubsub.closed is True


async def test_duplicate_seqs_from_pubsub_are_dropped(sessionmaker):
    job_id = await make_job_with_events(sessionmaker, ["analyzing", "captured"])
    live = [
        AgentEvent(seq=2, kind="captured", message="dup").to_json(),  # already replayed
        AgentEvent(seq=3, kind="live", message="done").to_json(),
    ]
    redis = FakeRedis(scripted=live)
    chunks = await collect(stream_job_events(sessionmaker, redis, job_id, max_seconds=5))
    kinds = [e["kind"] for e in parse_stream(chunks)]
    assert kinds == ["analyzing", "captured", "live"]


async def test_route_streams_replayed_events(api, sessionmaker):
    job_id = await make_job_with_events(sessionmaker, ["analyzing", "live"])
    async with api.stream("GET", f"/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    kinds = [e["kind"] for e in parse_stream(body.splitlines(keepends=False))]
    assert "analyzing" in kinds and "live" in kinds


async def test_route_404_for_unknown_job(api):
    import uuid

    resp = await api.get(f"/jobs/{uuid.uuid4()}/events")
    assert resp.status_code == 404
