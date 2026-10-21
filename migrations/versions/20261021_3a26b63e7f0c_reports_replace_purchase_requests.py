"""reports replace purchase requests

Revision ID: 3a26b63e7f0c
Revises: 83a3b0ba59d9
Create Date: 2026-10-21 16:04:26.592644
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3a26b63e7f0c"
down_revision: str | None = "83a3b0ba59d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_purchase_requests_status"), table_name="purchase_requests")
    op.drop_table("purchase_requests")
    op.add_column("tasks", sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "seen_at")
    op.create_table(
        "purchase_requests",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("text", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("status", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("machine_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("task_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("created_by_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_purchase_requests_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_purchase_requests_machine_id_machines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_purchase_requests_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_requests")),
    )
    op.create_index(
        op.f("ix_purchase_requests_status"), "purchase_requests", ["status"], unique=False
    )
