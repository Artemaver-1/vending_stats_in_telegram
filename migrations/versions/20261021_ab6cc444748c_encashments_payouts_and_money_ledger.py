"""encashments, payouts and money ledger

Revision ID: ab6cc444748c
Revises: b66dcfaa53c7
Create Date: 2026-10-21 17:33:13.963841
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab6cc444748c"
down_revision: str | None = "b66dcfaa53c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("bank_opening", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger")),
    )
    op.create_table(
        "payouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("recipient", sa.String(length=120), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payouts")),
    )
    op.create_index(op.f("ix_payouts_paid_on"), "payouts", ["paid_on"], unique=False)
    op.create_table(
        "encashments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "collected",
                "counted",
                "deposited",
                name="encashmentstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("took_bills", sa.Boolean(), nullable=False),
        sa.Column("took_coins", sa.Boolean(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_by_id", sa.Integer(), nullable=True),
        sa.Column("expected_bills", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("expected_coins", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("bills", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("coins", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counted_by_id", sa.Integer(), nullable=True),
        sa.Column("deposited", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("deposited_on", sa.Date(), nullable=True),
        sa.Column("deposited_by_id", sa.Integer(), nullable=True),
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
            ["collected_by_id"],
            ["users.id"],
            name=op.f("fk_encashments_collected_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["counted_by_id"],
            ["users.id"],
            name=op.f("fk_encashments_counted_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deposited_by_id"],
            ["users.id"],
            name=op.f("fk_encashments_deposited_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_encashments_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["tasks.id"],
            name=op.f("fk_encashments_report_id_tasks"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_encashments")),
    )
    op.create_index(
        op.f("ix_encashments_collected_at"), "encashments", ["collected_at"], unique=False
    )
    op.create_index(op.f("ix_encashments_status"), "encashments", ["status"], unique=False)
    op.add_column("tasks", sa.Column("encashment_id", sa.Integer(), nullable=True))
    op.alter_column("tasks", "due_on", existing_type=sa.DATE(), nullable=True)
    op.create_foreign_key(
        op.f("fk_tasks_encashment_id_encashments"),
        "tasks",
        "encashments",
        ["encashment_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_tasks_encashment_id_encashments"), "tasks", type_="foreignkey")
    op.alter_column("tasks", "due_on", existing_type=sa.DATE(), nullable=False)
    op.drop_column("tasks", "encashment_id")
    op.drop_index(op.f("ix_encashments_status"), table_name="encashments")
    op.drop_index(op.f("ix_encashments_collected_at"), table_name="encashments")
    op.drop_table("encashments")
    op.drop_index(op.f("ix_payouts_paid_on"), table_name="payouts")
    op.drop_table("payouts")
    op.drop_table("ledger")
