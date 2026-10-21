from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.db.models.location import Machine
from app.domain.enums import ExpenseCategory, PaymentChannel, RevenueSource


class DailyRevenue(TimestampMixin, Base):
    """Revenue of a machine for one day through one payment channel.

    Sync jobs recompute and upsert the whole row, so re-running an import is safe.
    """

    __tablename__ = "daily_revenue"
    __table_args__ = (UniqueConstraint("machine_id", "day", "channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(index=True)
    channel: Mapped[PaymentChannel] = mapped_column(str_enum(PaymentChannel))
    amount: Mapped[Decimal]
    sales_count: Mapped[int] = mapped_column(default=0)
    source: Mapped[RevenueSource] = mapped_column(str_enum(RevenueSource))

    machine: Mapped[Machine] = relationship()


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL means a shared expense that isn't tied to a particular machine.
    machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("machines.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[ExpenseCategory] = mapped_column(str_enum(ExpenseCategory))
    amount: Mapped[Decimal]
    spent_on: Mapped[date] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)

    machine: Mapped[Machine | None] = relationship()


class SyncState(Base):
    """Bookkeeping for external sources, so a sync after downtime knows where to resume."""

    __tablename__ = "sync_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    synced_through: Mapped[date | None]
    last_error: Mapped[str | None] = mapped_column(Text)
