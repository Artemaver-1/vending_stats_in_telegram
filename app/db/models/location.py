from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Location(TimestampMixin, Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    address: Mapped[str | None] = mapped_column(String(255))
    landlord: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(default=True)

    machines: Mapped[list["Machine"]] = relationship(back_populates="location")


class Machine(TimestampMixin, Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), unique=True)
    purchase_cost: Mapped[Decimal]
    launched_on: Mapped[date | None]
    is_active: Mapped[bool] = mapped_column(default=True)

    # Identifiers of the same machine in external systems, used to match synced data.
    vendista_terminal_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    telemetry_device_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Card revenue up to this day comes from the Vendista export, which has the bank's
    # dates; SmartVend only fills in the days after the latest export.
    vendista_covered_through: Mapped[date | None]

    # Last connection status seen in the telemetry, refreshed by the worker.
    is_online: Mapped[bool | None]
    status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Set when an inspection finds the whole machine down; cleared by a passing check.
    broken_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last day the team got the daily "machine is standing idle" message.
    down_alerted_on: Mapped[date | None]

    location: Mapped[Location | None] = relationship(back_populates="machines")

    @property
    def is_broken(self) -> bool:
        return self.broken_since is not None
