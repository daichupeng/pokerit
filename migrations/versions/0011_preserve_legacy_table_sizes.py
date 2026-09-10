"""Restore legacy MTT labels when the historical table was not 8-max.

Revision ID: 0011_legacy_table_sizes
Revises: 0010_8max_thresholds
Create Date: 2026-07-23
"""

from alembic import op


revision = "0011_legacy_table_sizes"
down_revision = "0010_8max_thresholds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0010 was briefly applied locally with an unconditional legacy rename.
    # Actual historical seat count is authoritative: a six-player game must
    # not become part of an 8-max coaching profile merely because code changed.
    op.execute("""
        UPDATE games g
        SET scenario = CASE g.scenario
                WHEN 'mtt_8max_40bb' THEN 'mtt_40bb'
                WHEN 'mtt_8max_25bb' THEN 'mtt_25bb'
                WHEN 'mtt_8max_15bb' THEN 'mtt_push_fold'
                ELSE g.scenario
            END,
            profile_scope = CASE g.scenario
                WHEN 'mtt_8max_40bb' THEN 'mtt_25_40bb'
                WHEN 'mtt_8max_25bb' THEN 'mtt_25_40bb'
                WHEN 'mtt_8max_15bb' THEN 'mtt_15bb'
                ELSE g.profile_scope
            END
        WHERE g.scenario IN ('mtt_8max_40bb', 'mtt_8max_25bb', 'mtt_8max_15bb')
          AND (SELECT COUNT(*) FROM game_players gp WHERE gp.game_id = g.id) <> 8
    """)


def downgrade() -> None:
    # Do not relabel historical table sizes incorrectly on downgrade.
    pass
