import uuid
from typing import Protocol


class JobQueue(Protocol):
    async def enqueue_analyze(self, job_id: uuid.UUID | str) -> None: ...


class ArqQueue:
    """Thin adapter so routes depend on a protocol, not on arq itself."""

    def __init__(self, pool):
        self._pool = pool

    async def enqueue_analyze(self, job_id: uuid.UUID | str) -> None:
        await self._pool.enqueue_job("analyze_job", str(job_id))
