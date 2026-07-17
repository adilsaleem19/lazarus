import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONColumn = sa.JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(sa.String(2048))
    status: Mapped[str] = mapped_column(sa.String(16), default="queued", index=True)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    final_html: Mapped[str] = mapped_column(sa.Text)
    skeleton: Mapped[str] = mapped_column(sa.Text)
    token_estimate: Mapped[int] = mapped_column(sa.Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    xhr: Mapped[list] = mapped_column(JSONColumn, default=list)
    structures: Mapped[list] = mapped_column(JSONColumn, default=list)
    robots_status: Mapped[str] = mapped_column(sa.String(16))
    robots_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class JobEvent(Base):
    """One step of the agent's reasoning, streamed live and kept for replay."""

    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(sa.Integer)
    kind: Mapped[str] = mapped_column(sa.String(32))
    message: Mapped[str] = mapped_column(sa.Text)
    data: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

    __table_args__ = (sa.UniqueConstraint("job_id", "seq", name="uq_job_events_job_seq"),)


class LLMCall(Base):
    """Full log of every prompt/response — feeds the 'watch it think' UI and cost tracking."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(sa.String(32))
    model: Mapped[str] = mapped_column(sa.String(128))
    purpose: Mapped[str] = mapped_column(sa.String(32))
    prompt: Mapped[str] = mapped_column(sa.Text)
    response: Mapped[str] = mapped_column(sa.Text)
    prompt_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Extractor(Base):
    """A validated scraper: the durable product of a successful agent run.

    Phase 3 turns each row into a live endpoint: `data` is the cached result set
    served by GET /api/{slug}, refreshed on a schedule. `status` lifecycle:
    active (serving + refreshing) -> paused (3 failed refreshes; still serves
    stale data) or evicted (LRU limit; endpoint gone).
    """

    __tablename__ = "extractors"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    slug: Mapped[str] = mapped_column(sa.String(128), index=True)
    source_url: Mapped[str] = mapped_column(sa.String(2048))
    strategy: Mapped[str] = mapped_column(sa.String(16))
    # For json_xhr: the hidden API URL whose response body extract() parses.
    # Refresh re-captures the page and re-matches this URL in the new XHR log.
    target: Mapped[str | None] = mapped_column(sa.String(2048))
    code: Mapped[str] = mapped_column(sa.Text)
    record_schema: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    sample: Mapped[list] = mapped_column(JSONColumn, default=list)
    data: Mapped[list] = mapped_column(JSONColumn, default=list)
    description: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="active", index=True)
    paused_reason: Mapped[str | None] = mapped_column(sa.Text)
    refresh_interval_minutes: Mapped[int] = mapped_column(sa.Integer, default=30)
    consecutive_failures: Mapped[int] = mapped_column(sa.Integer, default=0)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
