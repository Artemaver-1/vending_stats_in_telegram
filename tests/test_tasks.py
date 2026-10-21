from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Machine, Task, User
from app.domain.enums import TaskKind, TaskStatus, UserRole
from app.domain.inspection import CHECKLIST
from app.services.tasks import TaskError, TaskService
from tests.helpers import TZ, FixedClock

ALL_OK = {item.key: True for item in CHECKLIST}


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 21, 12, tzinfo=TZ))


@pytest.fixture
async def worker(session: AsyncSession) -> User:
    user = User(telegram_id=111, name="Вася", role=UserRole.WORKER, is_active=True)
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def machines(session: AsyncSession) -> list[Machine]:
    items = [
        Machine(name="Пушкина", purchase_cost=Decimal("320000")),
        Machine(name="Динамо", purchase_cost=Decimal("320000")),
        Machine(name="Старый", purchase_cost=Decimal("1"), is_active=False),
    ]
    session.add_all(items)
    await session.flush()
    return items


async def open_inspections(session: AsyncSession) -> list[Task]:
    result = await session.scalars(
        select(Task).where(Task.kind == TaskKind.INSPECTION, Task.status == TaskStatus.OPEN)
    )
    return list(result)


async def test_first_inspections_are_due_today_for_active_machines(
    session: AsyncSession, machines: list[Machine], clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    created = await service.schedule_inspections()
    again = await service.schedule_inspections()

    assert sorted(t.machine.name for t in created if t.machine) == ["Динамо", "Пушкина"]
    assert {t.due_on for t in created} == {date(2026, 10, 21)}
    assert again == []


async def test_report_closes_weekly_inspection_and_schedules_next(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    pushkina = machines[0]
    await service.schedule_inspections()

    outcome = await service.submit_report(pushkina, worker, ALL_OK)

    assert not outcome.needs_attention
    assert [c.label for c in outcome.task.checks] == [i.label for i in CHECKLIST]
    upcoming = [t for t in await open_inspections(session) if t.machine_id == pushkina.id]
    assert [t.due_on for t in upcoming] == [date(2026, 10, 28)]


async def test_report_without_pending_inspection_is_recorded_too(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    outcome = await service.submit_report(
        machines[1], worker, {**ALL_OK, "bill": False}, comment="Стекло треснуло"
    )
    assert outcome.needs_attention and outcome.failed == ["Купюроприёмник"]
    assert [r.comment for r in await service.reports(machines[1].id)] == ["Стекло треснуло"]


async def test_broken_machine_pauses_inspections_until_a_passing_report(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    pushkina = machines[0]
    await service.schedule_inspections()

    outcome = await service.submit_report(pushkina, worker, {**ALL_OK, "machine": False})
    assert outcome.machine_broke and pushkina.is_broken
    assert outcome.failed == ["Силомер"]

    clock.shift(days=10)
    await service.schedule_inspections()
    assert all(t.machine_id != pushkina.id for t in await open_inspections(session))

    fixed = await service.submit_report(pushkina, worker, ALL_OK)
    assert fixed.machine_fixed and not pushkina.is_broken
    upcoming = [t for t in await open_inspections(session) if t.machine_id == pushkina.id]
    assert [t.due_on for t in upcoming] == [clock.today() + timedelta(days=7)]


async def test_unseen_reports_counter(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    await service.submit_report(machines[0], worker, ALL_OK)
    await service.submit_report(machines[1], worker, ALL_OK)
    assert await service.count_unseen_reports() == 2

    await service.mark_reports_seen()
    assert await service.count_unseen_reports() == 0


async def test_report_needs_every_answer(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    with pytest.raises(TaskError, match="Не отмечено"):
        await TaskService(session, clock).submit_report(machines[0], worker, {"machine": True})


async def test_reminders_two_days_and_one_day_before_only(
    session: AsyncSession, worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    for days in (0, 1, 2, 3, -1):
        await service.create(
            title=f"через {days}", due_on=clock.today() + timedelta(days=days), author=worker
        )

    due = await service.due_reminders()
    assert sorted(t.title for t in due) == ["через 1", "через 2"]

    for task in due:
        task.reminded_on = clock.today()
    assert await service.due_reminders() == []


async def test_custom_task_completion(
    session: AsyncSession, worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    task = await service.create(title="Получить датчик", due_on=clock.today(), author=worker)
    await service.complete(task, worker, "  забрал  ")

    assert task.status is TaskStatus.DONE
    assert task.comment == "забрал"
    with pytest.raises(TaskError):
        await service.complete(task, worker)
