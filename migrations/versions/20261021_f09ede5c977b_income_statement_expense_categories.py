"""income statement expense categories

Revision ID: f09ede5c977b
Revises: 3a26b63e7f0c
Create Date: 2026-10-21 16:14:13.984258
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f09ede5c977b"
down_revision: str | None = "3a26b63e7f0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Acquiring fees and transport are no longer separate lines of the income statement.
    op.execute(
        "UPDATE expenses SET category = 'other' WHERE category IN ('acquiring_fee', 'transport')"
    )


def downgrade() -> None:
    # Categories that didn't exist before fall back to "other".
    op.execute(
        "UPDATE expenses SET category = 'other' "
        "WHERE category IN ('rent', 'smartvend', 'staff', 'taxes', 'insurance')"
    )
