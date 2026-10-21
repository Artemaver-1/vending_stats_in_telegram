from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.db.models.location import Machine
from app.domain.enums import EncashmentStatus, TaskKind, TaskStatus, UserRole


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.WORKER)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str | None] = mapped_column(String(64))
    # Someone who pressed /start but hasn't been let in by an admin yet.
    is_active: Mapped[bool] = mapped_column(default=False)

    @property
    def is_admin(self) -> bool:
        return self.is_active and self.role is UserRole.ADMIN


class Attachment(Base):
    """Small files such as pickup QR codes; kept in the database to avoid a file volume."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[TaskKind] = mapped_column(str_enum(TaskKind))
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus), default=TaskStatus.OPEN, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # NULL for tasks without a deadline, such as counting collected cash.
    due_on: Mapped[date | None] = mapped_column(index=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL")
    )
    encashment_id: Mapped[int | None] = mapped_column(
        ForeignKey("encashments.id", ondelete="CASCADE")
    )

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment: Mapped[str | None] = mapped_column(Text)
    reminded_on: Mapped[date | None]
    # When an admin first saw the finished report in "Инфа от работника".
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    machine: Mapped[Machine | None] = relationship()
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])
    attachment: Mapped[Attachment | None] = relationship()
    encashment: Mapped["Encashment | None"] = relationship(foreign_keys=[encashment_id])
    checks: Mapped[list["InspectionCheck"]] = relationship(
        back_populates="task", order_by="InspectionCheck.position", cascade="all, delete-orphan"
    )

    @property
    def is_open(self) -> bool:
        return self.status is TaskStatus.OPEN


class InspectionCheck(Base):
    __tablename__ = "inspection_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    item: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))
    ok: Mapped[bool]

    task: Mapped[Task] = relationship(back_populates="checks")


class Encashment(TimestampMixin, Base):
    """Cash taken out of a machine, followed until it lands on the bank account:
    collected during a visit, counted on a counting machine, then deposited."""

    __tablename__ = "encashments"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"))
    # tasks and encashments point at each other, so this side is added with ALTER.
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL", use_alter=True)
    )
    status: Mapped[EncashmentStatus] = mapped_column(
        str_enum(EncashmentStatus), default=EncashmentStatus.COLLECTED, index=True
    )
    took_bills: Mapped[bool]
    took_coins: Mapped[bool]
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    collected_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # What SmartVend says came in as cash since the previous collection, for comparison.
    expected_bills: Mapped[Decimal | None]
    expected_coins: Mapped[Decimal | None]

    bills: Mapped[Decimal | None]
    coins: Mapped[Decimal | None]
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    deposited: Mapped[Decimal | None]
    deposited_on: Mapped[date | None]
    deposited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    machine: Mapped[Machine] = relationship()
    collected_by: Mapped[User | None] = relationship(foreign_keys=[collected_by_id])
    counted_by: Mapped[User | None] = relationship(foreign_keys=[counted_by_id])
    deposited_by: Mapped[User | None] = relationship(foreign_keys=[deposited_by_id])

    @property
    def counted(self) -> Decimal | None:
        if self.bills is None and self.coins is None:
            return None
        return (self.bills or Decimal(0)) + (self.coins or Decimal(0))

    @property
    def expected(self) -> Decimal | None:
        parts = []
        if self.took_bills:
            parts.append(self.expected_bills)
        if self.took_coins:
            parts.append(self.expected_coins)
        if not parts or None in parts:
            return None
        return sum((p for p in parts if p is not None), Decimal(0))


class Payout(TimestampMixin, Base):
    """Money taken off the business bank account and handed to someone."""

    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    paid_on: Mapped[date] = mapped_column(index=True)
    amount: Mapped[Decimal]
    recipient: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)


class Ledger(Base):
    """Starting point of money tracking: balances are counted from this day on."""

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    opened_on: Mapped[date]
    bank_opening: Mapped[Decimal]
