"""Server-sent events for the live agent theater.

Strategy: replay everything already persisted (so reconnects and late joiners
see the full story), then follow the per-job Redis channel live. Events carry a
per-job seq, which makes the replay/live handoff idempotent — duplicates from
the race between the replay query and the subscription are dropped by seq.
"""

import asyncio
import json
import time

import sqlalchemy as sa

from app.events import AgentEvent, event_channel
from app.models import JobEvent

TERMINAL_KINDS = frozenset({"live", "failed", "captured_only"})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _row_payload(row: JobEvent) -> dict:
    return {
        "seq": row.seq,
        "kind": row.kind,
        "message": row.message,
        "data": row.data or {},
        "at": row.created_at.isoformat() if row.created_at else None,
    }


async def _persisted_events(sessionmaker, job_id, after_seq: int = 0) -> list[JobEvent]:
    async with sessionmaker() as session:
        stmt = (
            sa.select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq > after_seq)
            .order_by(JobEvent.seq)
        )
        return list((await session.execute(stmt)).scalars().all())


async def stream_job_events(
    sessionmaker,
    redis,
    job_id,
    *,
    max_seconds: float = 300,
    keepalive_s: float = 15,
):
    """Yield SSE-formatted strings for one job until its terminal event."""
    import uuid as _uuid

    job_uuid = _uuid.UUID(str(job_id))
    last_seq = 0

    for row in await _persisted_events(sessionmaker, job_uuid):
        last_seq = row.seq
        yield _sse(_row_payload(row))
        if row.kind in TERMINAL_KINDS:
            return

    if redis is None:
        return

    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(event_channel(str(job_id)))

        # Close the race: anything persisted between the replay query and the
        # subscription is in the DB but was published before we listened.
        for row in await _persisted_events(sessionmaker, job_uuid, after_seq=last_seq):
            last_seq = row.seq
            yield _sse(_row_payload(row))
            if row.kind in TERMINAL_KINDS:
                return

        deadline = time.monotonic() + max_seconds
        last_beat = time.monotonic()
        while time.monotonic() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                if time.monotonic() - last_beat >= keepalive_s:
                    last_beat = time.monotonic()
                    yield ": keepalive\n\n"
                await asyncio.sleep(0)  # let fakes with no delay cooperate
                continue
            event = AgentEvent.from_json(message["data"])
            if event.seq <= last_seq:
                continue
            last_seq = event.seq
            yield _sse(
                {"seq": event.seq, "kind": event.kind, "message": event.message,
                 "data": event.data, "at": None}
            )
            if event.kind in TERMINAL_KINDS:
                return
    finally:
        try:
            await pubsub.unsubscribe(event_channel(str(job_id)))
            await pubsub.aclose()
        except Exception:  # noqa: BLE001 — never let cleanup kill the response
            pass
