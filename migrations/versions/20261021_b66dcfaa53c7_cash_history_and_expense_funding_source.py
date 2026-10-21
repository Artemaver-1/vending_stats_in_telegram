"""cash history and expense funding source

Revision ID: b66dcfaa53c7
Revises: 0d503ba598b4
Create Date: 2026-10-21 17:28:39.550197
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b66dcfaa53c7"
down_revision: str | None = "0d503ba598b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cash_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.Column("coins", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("bills", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_cash_history_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_history")),
    )
    op.add_column(
        "expenses",
        sa.Column(
            "paid_from",
            sa.Enum("bank", "cash", "personal", name="paidfrom", native_enum=False, length=32),
            server_default="personal",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("expenses", "paid_from")
    op.drop_table("cash_history")
