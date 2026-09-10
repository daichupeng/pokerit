"""Separate showdown occurrence from card visibility and backfill hand data.

Revision ID: 0013_fix_showdown_visibility
Revises: 0012_history_evaluations
Create Date: 2026-07-23
"""

from alembic import op


revision = "0013_fix_showdown_visibility"
down_revision = "0012_history_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy persists native Enum member names, not their display values.
    op.execute("ALTER TYPE botstyle ADD VALUE IF NOT EXISTS 'AI_GTO'")
    op.execute("ALTER TYPE botstyle ADD VALUE IF NOT EXISTS 'AI_FISH'")
    op.execute("ALTER TYPE botstyle ADD VALUE IF NOT EXISTS 'AI_STATION'")

    # A real showdown has at least two players from the dealt hand who never
    # folded. ``starting_stack > 0`` excludes busted/sitting-out seats, whose
    # persisted hand-player rows still exist with a zero stack.
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

    # Fold winners were previously marked revealed merely because PokerKit
    # retained their cards. Keep the hero's own cards, preserve genuine
    # showdown visibility, and remove every hidden opponent hand from storage.
    op.execute(
        """
        UPDATE hand_players AS hp
        SET revealed = CASE
            WHEN gp.is_bot = FALSE THEN TRUE
            WHEN h.had_showdown = FALSE THEN FALSE
            ELSE hp.revealed
        END
        FROM game_players AS gp, hands AS h
        WHERE gp.id = hp.game_player_id
          AND h.id = hp.hand_id
        """
    )
    op.execute(
        """
        UPDATE hand_players AS hp
        SET hole_cards = NULL
        FROM game_players AS gp
        WHERE gp.id = hp.game_player_id
          AND gp.is_bot = TRUE
          AND hp.revealed = FALSE
        """
    )


def downgrade() -> None:
    # Hidden cards intentionally cannot be reconstructed. PostgreSQL enum
    # labels are likewise left in place because removing them requires a type
    # rebuild and existing rows may already use them.
    pass
