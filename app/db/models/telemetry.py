from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.models.location import Machine
from app.domain.enums import PaymentChannel


class TelemetrySale(Base):
    """A single sale as reported by the SmartVend controller.

    Raw sales are kept so daily revenue can be rebuilt when the controller uploads
    sales it recorded while offline.
    """

    __tablename__ = "telemetry_sales"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bill: Mapped[Decimal]
    coin: Mapped[Decimal]
    card: Mapped[Decimal]
    canceled: Mapped[bool] = mapped_column(default=False)

    machine: Mapped[Machine] = relationship()


class ConnectionEvent(Base):
    __tablename__ = "connection_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    online: Mapped[bool]
    notified: Mapped[bool] = mapped_column(default=False)

    machine: Mapped[Machine] = relationship()


class EstimatedUptime(Base):
    """Whether a machine worked on a day before SmartVend reported its connection,
    judged by card payments on the Vendista terminal."""

    __tablename__ = "estimated_uptime"

    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(primary_key=True)
    worked: Mapped[bool]


class PaymentAlert(Base):
    """A payment method nobody has paid with for a while although the machine keeps
    selling, which usually means its acceptor or terminal is broken."""

    __tablename__ = "payment_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[PaymentChannel] = mapped_column(str_enum(PaymentChannel))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recent_sales: Mapped[int]
    recent_hits: Mapped[int]
    # Length of the window the two counts above cover; it is longer in winter.
    quiet_days: Mapped[int]

    machine: Mapped[Machine] = relationship()

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
