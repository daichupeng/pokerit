"""Add training scenarios and scope long-term coaching profiles.

Revision ID: 0009_training_scenarios
Revises: 0008_player_profiles
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_training_scenarios"
down_revision = "0008_player_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("game_format", sa.String(length=20), nullable=False, server_default="cash"))
    op.add_column("games", sa.Column("scenario", sa.String(length=40), nullable=False, server_default="custom"))
    op.add_column("games", sa.Column("ante_type", sa.String(length=20), nullable=False, server_default="none"))
    op.add_column("games", sa.Column("tournament_stage", sa.String(length=30), nullable=True))
    op.add_column(
        "games",
        sa.Column("profile_scope", sa.String(length=40), nullable=False, server_default="cash_100bb"),
    )
    op.create_index("ix_games_profile_scope", "games", ["profile_scope"], unique=False)

    op.add_column(
        "player_profiles",
        sa.Column("scope_key", sa.String(length=40), nullable=False, server_default="cash_100bb"),
    )
    op.drop_constraint("player_profiles_pkey", "player_profiles", type_="primary")
    op.create_primary_key("player_profiles_pkey", "player_profiles", ["user_id", "scope_key"])


def downgrade() -> None:
    # A pre-scenario schema can hold only one profile per user. Preserve the
    # default cash profile and discard other scoped rows during downgrade.
    op.execute("DELETE FROM player_profiles WHERE scope_key <> 'cash_100bb'")
    op.drop_constraint("player_profiles_pkey", "player_profiles", type_="primary")
    op.create_primary_key("player_profiles_pkey", "player_profiles", ["user_id"])
    op.drop_column("player_profiles", "scope_key")

    op.drop_index("ix_games_profile_scope", table_name="games")
    op.drop_column("games", "profile_scope")
    op.drop_column("games", "tournament_stage")
    op.drop_column("games", "ante_type")
    op.drop_column("games", "scenario")
    op.drop_column("games", "game_format")
