from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.db.models.location import Location, Machine
from app.domain.enums import LeadActivityKind, LeadStatus, MilestoneKind


class Lead(TimestampMixin, Base):
    """A potential location and the landlord we're negotiating with."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    place: Mapped[str] = mapped_column(String(160))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[LeadStatus] = mapped_column(
        str_enum(LeadStatus), default=LeadStatus.NEW, index=True
    )
    next_contact_on: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)

    activities: Mapped[list["LeadActivity"]] = relationship(
        back_populates="lead", order_by="LeadActivity.occurred_at.desc()"
    )


class LeadActivity(TimestampMixin, Base):
    __tablename__ = "lead_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    kind: Mapped[LeadActivityKind] = mapped_column(str_enum(LeadActivityKind))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    outcome: Mapped[str | None] = mapped_column(Text)

    lead: Mapped[Lead] = relationship(back_populates="activities")


class Milestone(TimestampMixin, Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[MilestoneKind] = mapped_column(str_enum(MilestoneKind))
    occurred_on: Mapped[date] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"))

    location: Mapped[Location | None] = relationship()
    machine: Mapped[Machine | None] = relationship()
