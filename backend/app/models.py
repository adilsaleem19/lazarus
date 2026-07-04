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
