"""Add player_profiles and correction-loop columns on game_evaluations
(long-term coaching memory + discard/dispute/viewed/fold bookkeeping).

Revision ID: 0008_player_profiles
Revises: 0007_game_evaluations
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_player_profiles"
down_revision = "0007_game_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_evaluations",
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "game_evaluations",
        sa.Column("disputed_tags", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "game_evaluations",
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "game_evaluations",
        sa.Column("folded_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "player_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("evaluations_folded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leaks", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("playstyle_summary", sa.Text(), nullable=True),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_versions", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("player_profiles")

    op.drop_column("game_evaluations", "folded_at")
    op.drop_column("game_evaluations", "viewed_at")
    op.drop_column("game_evaluations", "disputed_tags")
    op.drop_column("game_evaluations", "discarded_at")
