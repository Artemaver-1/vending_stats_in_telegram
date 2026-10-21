"""payment method alerts and widget tokens

Revision ID: aebd21fe9825
Revises: 15a49945b6c0
Create Date: 2026-10-21 20:51:56.018633
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aebd21fe9825"
down_revision: str | None = "15a49945b6c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("card", "coin", "bill", name="paymentchannel", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recent_sales", sa.Integer(), nullable=False),
        sa.Column("recent_hits", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_payment_alerts_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_alerts")),
    )
    op.create_index(
        op.f("ix_payment_alerts_machine_id"), "payment_alerts", ["machine_id"], unique=False
    )
    op.add_column("users", sa.Column("widget_token", sa.String(length=64), nullable=True))
    op.create_unique_constraint(op.f("uq_users_widget_token"), "users", ["widget_token"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_widget_token"), "users", type_="unique")
    op.drop_column("users", "widget_token")
    op.drop_index(op.f("ix_payment_alerts_machine_id"), table_name="payment_alerts")
    op.drop_table("payment_alerts")
