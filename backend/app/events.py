"""Agent event stream: persist each reasoning step and fan it out over Redis pub/sub.

Every step of the agent loop emits one event. Events are numbered per job (seq),
stored in job_events for replay, and published to a per-job Redis channel that the
SSE endpoint (Phase 4) subscribes to for the live "watch it think" theater.
"""

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from app.models import JobEvent


def event_channel(job_id: str) -> str:
    return f"lazarus:events:{job_id}"


@dataclass
class AgentEvent:
    seq: int
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "AgentEvent":
        payload = json.loads(raw)
        return cls(
            seq=payload["seq"],
            kind=payload["kind"],
            message=payload["message"],
            data=payload.get("data", {}),
        )


class Emitter(Protocol):
    async def emit(self, kind: str, message: str, data: dict | None = None) -> None: ...


class EventEmitter:
    def __init__(self, job_id: str, sessionmaker, redis=None):
        self._job_id = job_id
        self._job_uuid = uuid.UUID(job_id)
        self._sessionmaker = sessionmaker
        self._redis = redis
        self._seq = 0

    async def emit(self, kind: str, message: str, data: dict | None = None) -> AgentEvent:
        self._seq += 1
        event = AgentEvent(seq=self._seq, kind=kind, message=message, data=data or {})

        async with self._sessionmaker() as session:
            session.add(
                JobEvent(
                    job_id=self._job_uuid,
                    seq=event.seq,
                    kind=event.kind,
                    message=event.message,
                    data=event.data,
                )
            )
            await session.commit()

        if self._redis is not None:
            await self._redis.publish(event_channel(self._job_id), event.to_json())
        return event
