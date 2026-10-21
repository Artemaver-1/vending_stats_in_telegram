"""uptime estimated from vendista payments

Revision ID: 0d503ba598b4
Revises: ff8a9b4d75a6
Create Date: 2026-10-21 17:24:37.851174
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0d503ba598b4"
down_revision: str | None = "ff8a9b4d75a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "estimated_uptime",
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("worked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_estimated_uptime_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("machine_id", "day", name=op.f("pk_estimated_uptime")),
    )


def downgrade() -> None:
    op.drop_table("estimated_uptime")
