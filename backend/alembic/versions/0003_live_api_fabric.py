"""live API fabric: extractor cache/lifecycle/refresh columns

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extractors", sa.Column("target", sa.String(2048), nullable=True))
    op.add_column(
        "extractors",
        sa.Column("data", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "extractors", sa.Column("description", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "extractors",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column("extractors", sa.Column("paused_reason", sa.Text(), nullable=True))
    op.add_column(
        "extractors",
        sa.Column(
            "refresh_interval_minutes", sa.Integer(), nullable=False, server_default="30"
        ),
    )
    op.add_column(
        "extractors",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extractors", sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "extractors", sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_extractors_status", "extractors", ["status"])


def downgrade() -> None:
    op.drop_index("ix_extractors_status", "extractors")
    for column in (
        "last_accessed_at",
        "last_refreshed_at",
        "consecutive_failures",
        "refresh_interval_minutes",
        "paused_reason",
        "status",
        "description",
        "data",
        "target",
    ):
        op.drop_column("extractors", column)
