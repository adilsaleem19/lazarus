from datetime import datetime

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    # The "I'll use this responsibly" checkbox: the UI posts it, the API enforces it.
    responsible_use: bool = False


class SnapshotSummary(BaseModel):
    token_estimate: int
    xhr_count: int
    structures: list[dict]
    robots_status: str


class JobOut(BaseModel):
    id: str
    url: str
    status: str
    reason: str | None = None
    created_at: datetime
    snapshot: SnapshotSummary | None = None


class SnapshotDetail(BaseModel):
    skeleton: str
    token_estimate: int
    meta: dict
    xhr: list[dict]
    structures: list[dict]
    robots_status: str
    robots_reason: str | None = None
