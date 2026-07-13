"""Add game_evaluations and game_evaluation_batches (async coach-agent pipeline).

Revision ID: 0007_game_evaluations
Revises: 0006_conversation_entry_point
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_game_evaluations"
down_revision = "0006_conversation_entry_point"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    evaluation_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", name="evaluationstatus", create_type=False
    )
    batch_status = postgresql.ENUM(
        "PENDING", "COMPLETED", "FAILED", name="batchstatus", create_type=False
    )
    postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", name="evaluationstatus"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("PENDING", "COMPLETED", "FAILED", name="batchstatus").create(bind, checkfirst=True)

    op.create_table(
        "game_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", evaluation_status, nullable=False, server_default="PENDING"),
        sa.Column("stats_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("leak_tags", postgresql.JSONB(), nullable=True),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("model_versions", postgresql.JSONB(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_stage", sa.String(length=20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_game_evaluations_game_id", "game_evaluations", ["game_id"])

    op.create_table(
        "game_evaluation_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("game_evaluations.id"), nullable=False,
        ),
        sa.Column("agent", sa.String(length=10), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("status", batch_status, nullable=False, server_default="PENDING"),
        sa.Column("hand_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("evaluation_id", "agent", "batch_index", name="uq_eval_agent_batch"),
    )
    op.create_index("ix_game_evaluation_batches_evaluation_id", "game_evaluation_batches", ["evaluation_id"])


def downgrade() -> None:
    op.drop_index("ix_game_evaluation_batches_evaluation_id", table_name="game_evaluation_batches")
    op.drop_table("game_evaluation_batches")
    op.drop_index("ix_game_evaluations_game_id", table_name="game_evaluations")
    op.drop_table("game_evaluations")

    bind = op.get_bind()
    for name in ("batchstatus", "evaluationstatus"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
