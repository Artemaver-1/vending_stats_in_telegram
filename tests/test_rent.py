from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyRevenue, Location, Machine
from app.domain.enums import PaymentChannel, RentType, RevenueSource
from app.services.rent import ContractTerms, RentError, RentService
from tests.helpers import TZ, FixedClock


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 14, 12, tzinfo=TZ))


@pytest.fixture
async def place(session: AsyncSession) -> Location:
    location = Location(name="Пушкина")
    session.add(location)
    await session.flush()
    machine = Machine(name="Пушкина", location_id=location.id, purchase_cost=Decimal("320000"))
    session.add(machine)
    await session.flush()
    session.add(
        DailyRevenue(
            machine_id=machine.id,
            day=date(2026, 9, 3),
            channel=PaymentChannel.CARD,
            amount=Decimal("15000"),
            source=RevenueSource.TELEMETRY,
        )
    )
    await session.flush()
    return location


async def test_accruals_for_closed_months_with_due_dates(
    session: AsyncSession, place: Location, clock: FixedClock
) -> None:
    rent = RentService(session, clock)
    await rent.save_contract(
        ContractTerms(place.id, RentType.PERCENT, Decimal("20"), 15, date(2026, 8, 1))
    )

    payments = sorted(await rent.payments(), key=lambda p: p.period)
    assert [(p.period, p.amount, p.due_on) for p in payments] == [
        (date(2026, 8, 1), Decimal("0.00"), date(2026, 9, 15)),
        (date(2026, 9, 1), Decimal("3000.00"), date(2026, 10, 15)),
    ]
    # October is still running, so it's only an estimate.
    upcoming = await rent.upcoming()
    assert [(u.period, u.due_on) for u in upcoming] == [(date(2026, 10, 1), date(2026, 11, 15))]


async def test_paid_amount_is_frozen_but_unpaid_is_recalculated(
    session: AsyncSession, place: Location, clock: FixedClock
) -> None:
    rent = RentService(session, clock)
    await rent.save_contract(
        ContractTerms(place.id, RentType.PERCENT, Decimal("20"), 15, date(2026, 9, 1))
    )
    (september,) = await rent.payments()
    await rent.set_paid(september, True)

    machine = await session.scalar(select(Machine))
    assert machine is not None
    session.add(
        DailyRevenue(
            machine_id=machine.id,
            day=date(2026, 9, 20),
            channel=PaymentChannel.BILL,
            amount=Decimal("5000"),
            source=RevenueSource.TELEMETRY,
        )
    )
    await rent.sync_accruals()
    assert september.amount == Decimal("3000.00")

    await rent.set_paid(september, False)
    await rent.sync_accruals()
    assert september.amount == Decimal("4000.00")


async def test_reminders_two_days_and_one_day_before(
    session: AsyncSession, place: Location, clock: FixedClock
) -> None:
    rent = RentService(session, clock)
    await rent.save_contract(
        ContractTerms(place.id, RentType.FIXED, Decimal("12000"), 16, date(2026, 9, 1))
    )
    assert [p.due_on for p in await rent.due_reminders()] == [date(2026, 10, 16)]

    clock.shift(days=2)
    assert await rent.due_reminders() == []


@pytest.mark.parametrize(
    ("rent_type", "amount", "day"),
    [(RentType.FIXED, "0", 15), (RentType.PERCENT, "120", 15), (RentType.FIXED, "100", 31)],
)
async def test_invalid_terms(
    session: AsyncSession,
    place: Location,
    clock: FixedClock,
    rent_type: RentType,
    amount: str,
    day: int,
) -> None:
    with pytest.raises(RentError):
        await RentService(session, clock).save_contract(
            ContractTerms(place.id, rent_type, Decimal(amount), day, date(2026, 9, 1))
        )
