"""initial schema

Revision ID: fa9f50fea3a1
Revises:
Create Date: 2026-10-21 13:56:23.345368
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fa9f50fea3a1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("place", sa.String(length=160), nullable=False),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "contacted",
                "negotiating",
                "agreed",
                "postponed",
                "rejected",
                name="leadstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("next_contact_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
    )
    op.create_index(op.f("ix_leads_status"), "leads", ["status"], unique=False)
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("landlord", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint("name", name=op.f("uq_locations_name")),
    )
    op.create_table(
        "sync_state",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("synced_through", sa.Date(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_sync_state")),
    )
    op.create_table(
        "lead_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "call",
                "message",
                "meeting",
                "visit",
                name="leadactivitykind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
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
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_lead_activities_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_activities")),
    )
    op.create_index(
        op.f("ix_lead_activities_lead_id"), "lead_activities", ["lead_id"], unique=False
    )
    op.create_index(
        op.f("ix_lead_activities_occurred_at"), "lead_activities", ["occurred_at"], unique=False
    )
    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("purchase_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("launched_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("vendista_terminal_id", sa.String(length=64), nullable=True),
        sa.Column("telemetry_device_id", sa.String(length=64), nullable=True),
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
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_machines_location_id_locations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machines")),
        sa.UniqueConstraint("name", name=op.f("uq_machines_name")),
        sa.UniqueConstraint("telemetry_device_id", name=op.f("uq_machines_telemetry_device_id")),
        sa.UniqueConstraint("vendista_terminal_id", name=op.f("uq_machines_vendista_terminal_id")),
    )
    op.create_index(op.f("ix_machines_location_id"), "machines", ["location_id"], unique=False)
    op.create_table(
        "rent_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column(
            "rent_type",
            sa.Enum("fixed", "percent", name="renttype", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("fixed_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("revenue_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("payment_day", sa.SmallInteger(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
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
        sa.CheckConstraint(
            "(rent_type = 'fixed' AND fixed_amount IS NOT NULL) OR (rent_type = 'percent' AND revenue_percent IS NOT NULL)",
            name=op.f("ck_rent_contracts_terms_match_type"),
        ),
        sa.CheckConstraint(
            "payment_day BETWEEN 1 AND 28", name=op.f("ck_rent_contracts_payment_day_range")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_rent_contracts_location_id_locations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rent_contracts")),
    )
    op.create_index(
        op.f("ix_rent_contracts_location_id"), "rent_contracts", ["location_id"], unique=False
    )
    op.create_table(
        "daily_revenue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("card", "coin", "bill", name="paymentchannel", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("sales_count", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "vendista",
                "telemetry",
                "manual",
                name="revenuesource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
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
            name=op.f("fk_daily_revenue_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_revenue")),
        sa.UniqueConstraint(
            "machine_id", "day", "channel", name=op.f("uq_daily_revenue_machine_id_day_channel")
        ),
    )
    op.create_index(op.f("ix_daily_revenue_day"), "daily_revenue", ["day"], unique=False)
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "parts",
                "repair",
                "acquiring_fee",
                "connectivity",
                "transport",
                "other",
                name="expensecategory",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
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
            name=op.f("fk_expenses_machine_id_machines"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(op.f("ix_expenses_machine_id"), "expenses", ["machine_id"], unique=False)
    op.create_index(op.f("ix_expenses_spent_on"), "expenses", ["spent_on"], unique=False)
    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "machine_launched",
                "payback_reached",
                "location_agreed",
                "contract_signed",
                "other",
                name="milestonekind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("machine_id", sa.Integer(), nullable=True),
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
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_milestones_location_id_locations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_milestones_machine_id_machines"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_milestones")),
    )
    op.create_index(op.f("ix_milestones_occurred_on"), "milestones", ["occurred_on"], unique=False)
    op.create_table(
        "rent_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
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
            ["contract_id"],
            ["rent_contracts.id"],
            name=op.f("fk_rent_payments_contract_id_rent_contracts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rent_payments")),
        sa.UniqueConstraint(
            "contract_id", "period", name=op.f("uq_rent_payments_contract_id_period")
        ),
    )


def downgrade() -> None:
    op.drop_table("rent_payments")
    op.drop_index(op.f("ix_milestones_occurred_on"), table_name="milestones")
    op.drop_table("milestones")
    op.drop_index(op.f("ix_expenses_spent_on"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_machine_id"), table_name="expenses")
    op.drop_table("expenses")
    op.drop_index(op.f("ix_daily_revenue_day"), table_name="daily_revenue")
    op.drop_table("daily_revenue")
    op.drop_index(op.f("ix_rent_contracts_location_id"), table_name="rent_contracts")
    op.drop_table("rent_contracts")
    op.drop_index(op.f("ix_machines_location_id"), table_name="machines")
    op.drop_table("machines")
    op.drop_index(op.f("ix_lead_activities_occurred_at"), table_name="lead_activities")
    op.drop_index(op.f("ix_lead_activities_lead_id"), table_name="lead_activities")
    op.drop_table("lead_activities")
    op.drop_table("sync_state")
    op.drop_table("locations")
    op.drop_index(op.f("ix_leads_status"), table_name="leads")
    op.drop_table("leads")
