"""outgoing files

Revision ID: 7d41c0e9a2b3
Revises: 5c2e8d1a7b40
Create Date: 2026-10-22 03:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d41c0e9a2b3"
down_revision: str | None = "5c2e8d1a7b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outgoing_files",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outgoing_files")),
    )


def downgrade() -> None:
    op.drop_table("outgoing_files")
