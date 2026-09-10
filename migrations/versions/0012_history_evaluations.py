"""Add scope-isolated rolling history evaluations.

Revision ID: 0012_history_evaluations
Revises: 0011_legacy_table_sizes
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_history_evaluations"
down_revision = "0011_legacy_table_sizes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    evaluation_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED",
        name="evaluationstatus", create_type=False,
    )
    op.create_table(
        "history_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope_key", sa.String(length=40), nullable=False),
        sa.Column("window_hands", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("latest_game_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("games.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("games_included", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", evaluation_status, nullable=False, server_default="PENDING"),
        sa.Column("stats_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("sample_status", postgresql.JSONB(), nullable=True),
        sa.Column("trend_comparison", postgresql.JSONB(), nullable=True),
        sa.Column("deterministic_stat_leaks", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("model_versions", postgresql.JSONB(), nullable=True),
        sa.Column("threshold_profile", sa.String(length=40), nullable=False),
        sa.Column("threshold_version", sa.String(length=40), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_history_evaluations_user_id", "history_evaluations", ["user_id"])
    op.create_index("ix_history_evaluations_scope_key", "history_evaluations", ["scope_key"])


def downgrade() -> None:
    op.drop_index("ix_history_evaluations_scope_key", table_name="history_evaluations")
    op.drop_index("ix_history_evaluations_user_id", table_name="history_evaluations")
    op.drop_table("history_evaluations")
