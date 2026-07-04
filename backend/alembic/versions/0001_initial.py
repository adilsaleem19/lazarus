"""initial jobs and page_snapshots tables

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("final_html", sa.Text(), nullable=False),
        sa.Column("skeleton", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("meta", JSONB(), nullable=False),
        sa.Column("xhr", JSONB(), nullable=False),
        sa.Column("structures", JSONB(), nullable=False),
        sa.Column("robots_status", sa.String(16), nullable=False),
        sa.Column("robots_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_page_snapshots_job_id", "page_snapshots", ["job_id"])


def downgrade() -> None:
    op.drop_table("page_snapshots")
    op.drop_table("jobs")
