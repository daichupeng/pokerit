"""Add position column to hand_players and truncate all existing data.

Revision ID: 0005_hand_player_position
Revises: 0004_action_stack_after
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_hand_player_position"
down_revision = "0004_action_stack_after"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Truncate all game data — positions cannot be backfilled.
    op.execute("TRUNCATE TABLE actions CASCADE")
    op.execute("TRUNCATE TABLE hand_players CASCADE")
    op.execute("TRUNCATE TABLE hands CASCADE")
    op.execute("TRUNCATE TABLE game_players CASCADE")
    op.execute("TRUNCATE TABLE games CASCADE")

    op.add_column(
        "hand_players",
        sa.Column("position", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hand_players", "position")
