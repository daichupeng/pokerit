"""Add exact 6/8-max scenario and profile keys.

Revision ID: 0010_8max_thresholds
Revises: 0009_training_scenarios
Create Date: 2026-07-23
"""

from alembic import op


revision = "0010_8max_thresholds"
down_revision = "0009_training_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("games", "profile_scope", server_default="cash_6max_100bb")
    op.alter_column("player_profiles", "scope_key", server_default="cash_6max_100bb")

    op.execute("""
        UPDATE games
        SET scenario = CASE scenario
            WHEN 'cash_100bb' THEN 'cash_6max_100bb'
            ELSE scenario
        END,
        profile_scope = CASE scenario
            WHEN 'cash_100bb' THEN 'cash_6max_100bb'
            ELSE profile_scope
        END
        WHERE scenario = 'cash_100bb'
    """)

    # These two legacy buckets have an unambiguous destination. The old
    # combined mtt_25_40bb bucket is retained as legacy history because it
    # cannot be split accurately after the fact.
    op.execute("""
        UPDATE player_profiles
        SET scope_key = 'cash_6max_100bb'
        WHERE scope_key = 'cash_100bb'
          AND NOT EXISTS (
              SELECT 1 FROM player_profiles p2
              WHERE p2.user_id = player_profiles.user_id
                AND p2.scope_key = 'cash_6max_100bb'
          )
    """)
    op.execute("""
        UPDATE player_profiles
        SET scope_key = 'mtt_8max_15bb'
        WHERE scope_key = 'mtt_15bb'
          AND NOT EXISTS (
              SELECT 1 FROM player_profiles p2
              WHERE p2.user_id = player_profiles.user_id
                AND p2.scope_key = 'mtt_8max_15bb'
          )
    """)


def downgrade() -> None:
    op.execute("UPDATE games SET scenario = 'cash_100bb', profile_scope = 'cash_100bb' WHERE scenario = 'cash_6max_100bb'")
    op.execute("UPDATE games SET scenario = 'mtt_40bb', profile_scope = 'mtt_25_40bb' WHERE scenario = 'mtt_8max_40bb'")
    op.execute("UPDATE games SET scenario = 'mtt_25bb', profile_scope = 'mtt_25_40bb' WHERE scenario = 'mtt_8max_25bb'")
    op.execute("UPDATE games SET scenario = 'mtt_push_fold', profile_scope = 'mtt_15bb' WHERE scenario = 'mtt_8max_15bb'")
    op.alter_column("games", "profile_scope", server_default="cash_100bb")
    op.alter_column("player_profiles", "scope_key", server_default="cash_100bb")
