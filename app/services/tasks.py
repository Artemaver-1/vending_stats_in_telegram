from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import Clock
from app.db.models import Attachment, InspectionCheck, Machine, Task, User
from app.domain.enums import TaskKind, TaskStatus
from app.domain.inspection import CHECKLIST, INSPECTION_INTERVAL, MACHINE_WORKS, REMINDER_OFFSETS

TASK_DETAILS = (
    selectinload(Task.machine),
    selectinload(Task.assignee),
    selectinload(Task.completed_by),
    selectinload(Task.checks),
    # The file body is only needed when the image itself is requested.
    selectinload(Task.attachment).load_only(
        Attachment.id, Attachment.filename, Attachment.content_type
    ),
)


class TaskError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class NewAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(slots=True)
class InspectionOutcome:
    task: Task
    failed: list[str] = field(default_factory=list)
    machine_broke: bool = False
    machine_fixed: bool = False

    @property
    def needs_attention(self) -> bool:
        return bool(self.failed or self.task.comment)


class TaskService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def get(self, task_id: int) -> Task | None:
        return await self.session.scalar(
            select(Task).where(Task.id == task_id).options(*TASK_DETAILS)
        )

    async def open_for(self, user: User) -> Sequence[Task]:
        result = await self.session.scalars(
            select(Task)
            .where(
                Task.status == TaskStatus.OPEN,
                or_(Task.assignee_id.is_(None), Task.assignee_id == user.id),
            )
            .options(*TASK_DETAILS)
            .order_by(Task.due_on, Task.id)
        )
        return result.all()

    async def done_by(self, user: User, limit: int = 10) -> Sequence[Task]:
        result = await self.session.scalars(
            select(Task)
            .where(Task.status == TaskStatus.DONE, Task.completed_by_id == user.id)
            .options(*TASK_DETAILS)
            .order_by(Task.completed_at.desc())
            .limit(limit)
        )
        return result.all()

    async def with_status(self, status: TaskStatus, limit: int = 50) -> Sequence[Task]:
        order = Task.due_on if status is TaskStatus.OPEN else Task.completed_at.desc()
        result = await self.session.scalars(
            select(Task)
            .where(Task.status == status)
            .options(*TASK_DETAILS)
            .order_by(order, Task.id.desc())
            .limit(limit)
        )
        return result.all()

    async def create(
        self,
        *,
        title: str,
        due_on: date,
        author: User,
        description: str | None = None,
        machine_id: int | None = None,
        assignee_id: int | None = None,
        attachment: NewAttachment | None = None,
    ) -> Task:
        task = Task(
            kind=TaskKind.CUSTOM,
            title=title.strip(),
            description=(description or "").strip() or None,
            due_on=due_on,
            machine_id=machine_id,
            assignee_id=assignee_id,
            created_by_id=author.id,
        )
        if attachment is not None:
            task.attachment = Attachment(
                filename=attachment.filename,
                content_type=attachment.content_type,
                data=attachment.data,
                created_at=self.clock.now(),
            )
        self.session.add(task)
        await self.session.flush()
        return await self._reload(task)

    async def complete(self, task: Task, user: User, comment: str | None = None) -> Task:
        if not task.is_open:
            raise TaskError("Задача уже закрыта")
        if task.kind is TaskKind.INSPECTION:
            raise TaskError("Осмотр закрывается заполнением чек-листа")
        self._close(task, user, TaskStatus.DONE, comment)
        await self.session.flush()
        return task

    async def cancel(self, task: Task, user: User) -> None:
        if task.is_open:
            self._close(task, user, TaskStatus.CANCELED, None)
            await self.session.flush()

    async def submit_report(
        self,
        machine: Machine,
        user: User,
        results: Mapping[str, bool],
        *,
        comment: str | None = None,
    ) -> InspectionOutcome:
        """Records a visit to a machine.

        The report closes the machine's pending weekly inspection if there is one, so a
        visit made early still counts, and the next inspection is due a week later.
        """
        missing = [item.question for item in CHECKLIST if item.key not in results]
        if missing:
            raise TaskError("Не отмечено: " + ", ".join(missing))

        task = await self._open_inspection(machine.id)
        if task is None:
            task = await self._new_inspection(machine, self.clock.today())
        task = await self._reload(task)

        task.checks = [
            InspectionCheck(position=i, item=item.key, label=item.label, ok=results[item.key])
            for i, item in enumerate(CHECKLIST)
        ]
        self._close(task, user, TaskStatus.DONE, comment)
        outcome = InspectionOutcome(task=task, failed=[c.label for c in task.checks if not c.ok])

        works = results[MACHINE_WORKS.key]
        if not works and not machine.is_broken:
            machine.broken_since = self.clock.now()
            outcome.machine_broke = True
        elif works and machine.is_broken:
            machine.broken_since = None
            outcome.machine_fixed = True

        await self.session.flush()
        if not machine.is_broken:
            await self._schedule_for(machine)
        return outcome

    async def reports(self, machine_id: int | None = None, limit: int = 50) -> Sequence[Task]:
        stmt = (
            select(Task)
            .where(Task.kind == TaskKind.INSPECTION, Task.status == TaskStatus.DONE)
            .options(*TASK_DETAILS)
            .order_by(Task.completed_at.desc())
            .limit(limit)
        )
        if machine_id is not None:
            stmt = stmt.where(Task.machine_id == machine_id)
        result = await self.session.scalars(stmt)
        return result.all()

    async def count_unseen_reports(self) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.kind == TaskKind.INSPECTION,
                Task.status == TaskStatus.DONE,
                Task.seen_at.is_(None),
            )
        )
        return count or 0

    async def mark_reports_seen(self) -> None:
        await self.session.execute(
            update(Task)
            .where(
                Task.kind == TaskKind.INSPECTION,
                Task.status == TaskStatus.DONE,
                Task.seen_at.is_(None),
            )
            .values(seen_at=self.clock.now())
        )

    async def schedule_inspections(self) -> list[Task]:
        machines = await self.session.scalars(select(Machine).where(Machine.is_active))
        created = []
        for machine in machines:
            if not machine.is_broken and (task := await self._schedule_for(machine)):
                created.append(task)
        return created

    async def due_reminders(self) -> Sequence[Task]:
        today = self.clock.today()
        result = await self.session.scalars(
            select(Task)
            .where(Task.status == TaskStatus.OPEN)
            .options(*TASK_DETAILS)
            .order_by(Task.due_on)
        )
        return [
            task
            for task in result
            if (task.due_on - today).days in REMINDER_OFFSETS and task.reminded_on != today
        ]

    async def last_inspection(self, machine_id: int) -> Task | None:
        return await self.session.scalar(
            select(Task)
            .where(
                Task.machine_id == machine_id,
                Task.kind == TaskKind.INSPECTION,
                Task.status == TaskStatus.DONE,
            )
            .options(*TASK_DETAILS)
            .order_by(Task.completed_at.desc())
            .limit(1)
        )

    async def _schedule_for(self, machine: Machine) -> Task | None:
        if await self._open_inspection(machine.id) is not None:
            return None
        last = await self.last_inspection(machine.id)
        if last is None or last.completed_at is None:
            due = self.clock.today()
        else:
            due = last.completed_at.astimezone(self.clock.tz).date() + INSPECTION_INTERVAL
        return await self._new_inspection(machine, due)

    async def _open_inspection(self, machine_id: int) -> Task | None:
        return await self.session.scalar(
            select(Task).where(
                Task.machine_id == machine_id,
                Task.kind == TaskKind.INSPECTION,
                Task.status == TaskStatus.OPEN,
            )
        )

    async def _new_inspection(self, machine: Machine, due: date) -> Task:
        task = Task(
            kind=TaskKind.INSPECTION,
            title=f"Проверка силомера «{machine.name}»",
            due_on=due,
            machine_id=machine.id,
        )
        self.session.add(task)
        await self.session.flush()
        return await self._reload(task)

    async def _reload(self, task: Task) -> Task:
        reloaded = await self.get(task.id)
        assert reloaded is not None
        return reloaded

    def _close(self, task: Task, user: User, status: TaskStatus, comment: str | None) -> None:
        task.status = status
        task.completed_at = self.clock.now()
        task.completed_by_id = user.id
        task.comment = (comment or "").strip() or None
