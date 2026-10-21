from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.db.models.location import Location
from app.domain.enums import RentType
from app.domain.periods import next_month


class RentContract(TimestampMixin, Base):
    __tablename__ = "rent_contracts"
    __table_args__ = (
        CheckConstraint(
            "(rent_type = 'fixed' AND fixed_amount IS NOT NULL)"
            " OR (rent_type = 'percent' AND revenue_percent IS NOT NULL)",
            name="terms_match_type",
        ),
        CheckConstraint("payment_day BETWEEN 1 AND 28", name="payment_day_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    rent_type: Mapped[RentType] = mapped_column(str_enum(RentType))
    fixed_amount: Mapped[Decimal | None]
    revenue_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    payment_day: Mapped[int] = mapped_column(SmallInteger, default=15)
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]

    location: Mapped[Location] = relationship()
    payments: Mapped[list["RentPayment"]] = relationship(back_populates="contract")


class RentPayment(TimestampMixin, Base):
    """Rent accrued for one calendar month; `period` is always the first day of that month."""

    __tablename__ = "rent_payments"
    __table_args__ = (UniqueConstraint("contract_id", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("rent_contracts.id", ondelete="CASCADE"))
    period: Mapped[date]
    amount: Mapped[Decimal]
    paid_on: Mapped[date | None]
    reminded_on: Mapped[date | None]

    contract: Mapped[RentContract] = relationship(back_populates="payments")

    @property
    def is_paid(self) -> bool:
        return self.paid_on is not None

    @property
    def due_on(self) -> date:
        """Rent for a month is paid on the contract's payment day of the following month."""
        return next_month(self.period).replace(day=self.contract.payment_day)
