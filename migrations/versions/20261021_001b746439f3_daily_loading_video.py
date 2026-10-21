"""daily loading video

Revision ID: 001b746439f3
Revises: aebd21fe9825
Create Date: 2026-10-21 21:13:50.954948
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001b746439f3"
down_revision: str | None = "aebd21fe9825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("splash_seen_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "splash_seen_on")
