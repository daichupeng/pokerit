"""Account management: expand users + oauth_identities.

Adds profile/identity/lifecycle columns to ``users`` and creates the
``oauth_identities`` table (plus the supporting enum types). Designed to run on
a database that already has the original 6 game tables, so it only adds the new
columns/table and preserves all existing rows.

Revision ID: 0001_account_management
Revises:
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "0001_account_management"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # --- enum types (create explicitly; create_type=False so referencing them
    #     in add_column/create_table below does NOT re-emit CREATE TYPE) ---
    account_status = postgresql.ENUM(
        "ACTIVE", "SUSPENDED", "DELETED", name="accountstatus", create_type=False
    )
    user_role = postgresql.ENUM("USER", "ADMIN", name="userrole", create_type=False)
    auth_provider = postgresql.ENUM("GOOGLE", name="authprovider", create_type=False)
    postgresql.ENUM("ACTIVE", "SUSPENDED", "DELETED", name="accountstatus").create(bind, checkfirst=True)
    postgresql.ENUM("USER", "ADMIN", name="userrole").create(bind, checkfirst=True)
    postgresql.ENUM("GOOGLE", name="authprovider").create(bind, checkfirst=True)

    # --- expand users (all new columns nullable / defaulted, so existing
    #     rows remain valid) ---
    existing_user_columns = {col["name"] for col in inspector.get_columns("users")}

    def add_users_column(column: sa.Column) -> None:
        if column.name not in existing_user_columns:
            op.add_column("users", column)

    add_users_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    add_users_column(sa.Column("username", sa.String(length=40), nullable=True))
    add_users_column(sa.Column("avatar_url", sa.Text(), nullable=True))
    add_users_column(sa.Column("bio", sa.Text(), nullable=True))
    add_users_column(sa.Column("country", sa.String(length=2), nullable=True))
    add_users_column(sa.Column("timezone", sa.String(length=64), nullable=True))
    add_users_column(sa.Column("language", sa.String(length=10), nullable=True))
    add_users_column(sa.Column("preferences", postgresql.JSONB(), nullable=False, server_default="{}"))
    add_users_column(sa.Column("status", account_status, nullable=False, server_default="ACTIVE"))
    add_users_column(sa.Column("role", user_role, nullable=False, server_default="USER"))
    add_users_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    add_users_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    add_users_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    existing_user_constraints = {
        uc["name"] for uc in inspector.get_unique_constraints("users")
    }
    if "uq_users_username" not in existing_user_constraints:
        op.create_unique_constraint("uq_users_username", "users", ["username"])

    # --- oauth_identities ---
    if not inspector.has_table("oauth_identities"):
        op.create_table(
            "oauth_identities",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", auth_provider, nullable=False),
            sa.Column("provider_user_id", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("provider", "provider_user_id", name="uq_provider_subject"),
        )
        inspector = inspect(bind)

    existing_oauth_indexes = {
        idx["name"] for idx in inspector.get_indexes("oauth_identities")
    }
    if "ix_oauth_identities_user_id" not in existing_oauth_indexes:
        op.create_index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_identities_user_id", table_name="oauth_identities")
    op.drop_table("oauth_identities")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    for col in (
        "deleted_at", "last_login_at", "updated_at", "role", "status",
        "preferences", "language", "timezone", "country", "bio", "avatar_url",
        "username", "email_verified",
    ):
        op.drop_column("users", col)
    bind = op.get_bind()
    for name in ("authprovider", "userrole", "accountstatus"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
