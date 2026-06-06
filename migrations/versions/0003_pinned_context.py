"""Add pinned_context column to conversations.

Revision ID: 0003_pinned_context
Revises: 0002_conversations
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_pinned_context"
down_revision = "0002_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("pinned_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "pinned_context")
