from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.db.models.location import Machine
from app.domain.enums import PurchaseStatus, TaskKind, TaskStatus, UserRole


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
    due_on: Mapped[date] = mapped_column(index=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"))
    # NULL means any member of the service team can pick it up.
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL")
    )

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment: Mapped[str | None] = mapped_column(Text)
    reminded_on: Mapped[date | None]

    machine: Mapped[Machine | None] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])
    attachment: Mapped[Attachment | None] = relationship()
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


class PurchaseRequest(TimestampMixin, Base):
    __tablename__ = "purchase_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[PurchaseStatus] = mapped_column(
        str_enum(PurchaseStatus), default=PurchaseStatus.NEW, index=True
    )
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    machine: Mapped[Machine | None] = relationship()
    created_by: Mapped[User | None] = relationship()
