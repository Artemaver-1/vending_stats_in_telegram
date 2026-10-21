"""telemetry sales and connection events

Revision ID: 30f4705ea890
Revises: fa9f50fea3a1
Create Date: 2026-10-21 14:09:55.082543
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "30f4705ea890"
down_revision: str | None = "fa9f50fea3a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connection_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("notified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_connection_events_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connection_events")),
    )
    op.create_index(
        op.f("ix_connection_events_occurred_at"), "connection_events", ["occurred_at"], unique=False
    )
    op.create_table(
        "telemetry_sales",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bill", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("coin", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("card", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("canceled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_telemetry_sales_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_sales")),
    )
    op.create_index(
        op.f("ix_telemetry_sales_machine_id"), "telemetry_sales", ["machine_id"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_sales_sold_at"), "telemetry_sales", ["sold_at"], unique=False
    )
    op.add_column("machines", sa.Column("is_online", sa.Boolean(), nullable=True))
    op.add_column(
        "machines", sa.Column("status_checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("machines", "status_checked_at")
    op.drop_column("machines", "is_online")
    op.drop_index(op.f("ix_telemetry_sales_sold_at"), table_name="telemetry_sales")
    op.drop_index(op.f("ix_telemetry_sales_machine_id"), table_name="telemetry_sales")
    op.drop_table("telemetry_sales")
    op.drop_index(op.f("ix_connection_events_occurred_at"), table_name="connection_events")
    op.drop_table("connection_events")
