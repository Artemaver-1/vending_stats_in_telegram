"""vendista coverage per machine

Revision ID: ff8a9b4d75a6
Revises: 3e953cd5dc4f
Create Date: 2026-10-21 16:51:06.637301
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ff8a9b4d75a6"
down_revision: str | None = "3e953cd5dc4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("vendista_covered_through", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("machines", "vendista_covered_through")
