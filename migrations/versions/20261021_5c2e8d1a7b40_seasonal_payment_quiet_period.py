"""seasonal payment quiet period

Revision ID: 5c2e8d1a7b40
Revises: 001b746439f3
Create Date: 2026-10-21 23:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c2e8d1a7b40"
down_revision: str | None = "001b746439f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_alerts",
        sa.Column("quiet_days", sa.Integer(), nullable=False, server_default="2"),
    )
    op.alter_column("payment_alerts", "quiet_days", server_default=None)


def downgrade() -> None:
    op.drop_column("payment_alerts", "quiet_days")
