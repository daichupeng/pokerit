"""Exclude zero-stack seats from historical showdown reconstruction.

Revision ID: 0014_exclude_inactive_showdowns
Revises: 0013_fix_showdown_visibility
Create Date: 2026-07-23
"""

from alembic import op


revision = "0014_exclude_inactive_showdowns"
down_revision = "0013_fix_showdown_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0013 originally used IS NOT NULL.  Persisted rows for eliminated seats
    # carry starting_stack=0, so they must not count as live showdown players.
    # Repeating the calculation also makes this safe for databases that ran a
    # pre-release copy of 0013 before that predicate was tightened.
    op.execute(
        """
        UPDATE hands AS h
        SET had_showdown = (
            SELECT COUNT(*) >= 2
            FROM hand_players AS hp
            WHERE hp.hand_id = h.id
              AND hp.starting_stack > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM actions AS a
                  WHERE a.hand_id = h.id
                    AND a.game_player_id = hp.game_player_id
                    AND a.action = 'fold'
              )
        )
        """
    )
    op.execute(
        """
        UPDATE hand_players AS hp
        SET revealed = FALSE,
            hole_cards = NULL
        FROM game_players AS gp, hands AS h
        WHERE gp.id = hp.game_player_id
          AND h.id = hp.hand_id
          AND gp.is_bot = TRUE
          AND h.had_showdown = FALSE
        """
    )


def downgrade() -> None:
    # The corrected showdown facts and removed hidden cards are intentional
    # and cannot be reconstructed safely.
    pass
