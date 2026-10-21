"""daily downtime alert marker

Revision ID: 15a49945b6c0
Revises: ab6cc444748c
Create Date: 2026-10-21 18:00:42.026945
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "15a49945b6c0"
down_revision: str | None = "ab6cc444748c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        op.f("fk_encashments_report_id_tasks"),
        "encashments",
        "tasks",
        ["report_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("machines", sa.Column("down_alerted_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("machines", "down_alerted_on")
    op.drop_constraint(op.f("fk_encashments_report_id_tasks"), "encashments", type_="foreignkey")
