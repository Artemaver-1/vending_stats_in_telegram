from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Machine, PurchaseRequest, Task, User
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


async def test_passed_inspection_schedules_next_one_a_week_later(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    task = next(t for t in await service.schedule_inspections() if t.machine_id == machines[0].id)

    outcome = await service.submit_inspection(task, worker, ALL_OK)

    assert not outcome.needs_attention
    assert [c.ok for c in task.checks] == [True] * len(CHECKLIST)
    upcoming = [t for t in await open_inspections(session) if t.machine_id == machines[0].id]
    assert [t.due_on for t in upcoming] == [date(2026, 10, 28)]


async def test_broken_machine_pauses_inspections_until_repair_check(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    pushkina = machines[0]
    task = next(t for t in await service.schedule_inspections() if t.machine_id == pushkina.id)

    outcome = await service.submit_inspection(
        task, worker, {**ALL_OK, "machine": False}, order="Новая груша"
    )
    assert outcome.machine_broke and pushkina.is_broken
    assert outcome.failed == ["Силомер работает"]
    purchase = await session.scalar(select(PurchaseRequest))
    assert purchase is not None and purchase.text == "Новая груша"

    clock.shift(days=10)
    await service.schedule_inspections()
    assert all(t.machine_id != pushkina.id for t in await open_inspections(session))

    repair = await service.start_repair_check(pushkina)
    assert repair.due_on == clock.today()
    fixed = await service.submit_inspection(repair, worker, ALL_OK)
    assert fixed.machine_fixed and not pushkina.is_broken
    upcoming = [t for t in await open_inspections(session) if t.machine_id == pushkina.id]
    assert [t.due_on for t in upcoming] == [clock.today() + timedelta(days=7)]


async def test_inspection_needs_every_answer(
    session: AsyncSession, machines: list[Machine], worker: User, clock: FixedClock
) -> None:
    service = TaskService(session, clock)
    task = (await service.schedule_inspections())[0]
    with pytest.raises(TaskError, match="Не отмечено"):
        await service.submit_inspection(task, worker, {"machine": True})


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
