"""Store the number of active players for every hand.

Revision ID: 0015_hand_active_players
Revises: 0014_exclude_inactive_showdowns
Create Date: 2026-07-25
"""

import sqlalchemy as sa
from alembic import op


revision = "0015_hand_active_players"
down_revision = "0014_exclude_inactive_showdowns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hands", sa.Column("active_player_count", sa.Integer(), nullable=True))
    # Historical hand-player rows remain present for busted seats, but their
    # starting stack is zero. Count only players who were actually dealt in.
    op.execute(
        """
        UPDATE hands AS h
        SET active_player_count = (
            SELECT COUNT(*)
            FROM hand_players AS hp
            WHERE hp.hand_id = h.id
              AND hp.starting_stack > 0
        )
        """
    )


def downgrade() -> None:
    op.drop_column("hands", "active_player_count")
