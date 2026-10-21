"""tasks belong to the whole service team

Revision ID: 3e953cd5dc4f
Revises: f09ede5c977b
Create Date: 2026-10-21 16:23:51.917868
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3e953cd5dc4f"
down_revision: str | None = "f09ede5c977b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("fk_tasks_assignee_id_users"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "assignee_id")


def downgrade() -> None:
    op.add_column(
        "tasks", sa.Column("assignee_id", sa.INTEGER(), autoincrement=False, nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_tasks_assignee_id_users"),
        "tasks",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
