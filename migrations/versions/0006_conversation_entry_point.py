"""Add entry_point and hand_id to conversations.

Revision ID: 0006_conversation_entry_point
Revises: 0005_hand_player_position
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_conversation_entry_point"
down_revision = "0005_hand_player_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "entry_point",
            sa.String(32),
            nullable=False,
            server_default="generic",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "hand_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hands.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "hand_id")
    op.drop_column("conversations", "entry_point")
