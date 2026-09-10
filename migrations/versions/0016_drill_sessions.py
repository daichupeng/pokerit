"""Persist preflop boundary drill sessions.

Revision ID: 0016_drill_sessions
Revises: 0015_hand_active_players
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0016_drill_sessions"
down_revision = "0015_hand_active_players"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drill_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pack_id", sa.String(length=64), nullable=False),
        sa.Column("pack_version", sa.String(length=20), nullable=False),
        sa.Column("questions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("next_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_drill_sessions_user_id", "drill_sessions", ["user_id"])
    op.create_index("ix_drill_sessions_pack_id", "drill_sessions", ["pack_id"])


def downgrade() -> None:
    op.drop_index("ix_drill_sessions_pack_id", table_name="drill_sessions")
    op.drop_index("ix_drill_sessions_user_id", table_name="drill_sessions")
    op.drop_table("drill_sessions")
