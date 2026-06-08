"""Add stack_after to actions table.

Revision ID: 0004_action_stack_after
Revises: 0003_pinned_context
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_action_stack_after"
down_revision = "0003_pinned_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "actions",
        sa.Column("stack_after", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("actions", "stack_after")
