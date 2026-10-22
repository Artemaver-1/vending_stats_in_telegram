from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyRevenue, Expense, Location, Machine, RentContract
from app.domain.enums import ExpenseCategory, PaymentChannel, RentType, RevenueSource
from app.services.finance import FinanceService, MachineNotFoundError


@pytest.fixture
async def business(session: AsyncSession) -> dict[str, Machine]:
    garden = Location(name="Горсад им. Пушкина")
    dynamo = Location(name="Динамо")
    session.add_all([garden, dynamo])
    await session.flush()

    garden_machine = Machine(
        name="Силомер Горсад",
        location_id=garden.id,
        purchase_cost=Decimal("320000"),
        launched_on=date(2026, 6, 10),
    )
    dynamo_machine = Machine(
        name="Силомер Динамо",
        location_id=dynamo.id,
        purchase_cost=Decimal("320000"),
        launched_on=date(2026, 7, 1),
    )
    session.add_all([garden_machine, dynamo_machine])
    await session.flush()

    session.add_all(
        [
            RentContract(
                location_id=garden.id,
                rent_type=RentType.PERCENT,
                revenue_percent=Decimal("20"),
                valid_from=date(2026, 6, 1),
            ),
            RentContract(
                location_id=dynamo.id,
                rent_type=RentType.FIXED,
                fixed_amount=Decimal("12000"),
                valid_from=date(2026, 7, 1),
            ),
        ]
    )
    for machine, card, coin in ((garden_machine, "50000", "10000"), (dynamo_machine, "30000", "0")):
        session.add_all(
            [
                _revenue(machine, date(2026, 9, 5), PaymentChannel.CARD, card),
                _revenue(machine, date(2026, 9, 6), PaymentChannel.COIN, coin),
            ]
        )
    session.add_all(
        [
            Expense(
                machine_id=garden_machine.id,
                category=ExpenseCategory.REPAIR,
                amount=Decimal("4000"),
                spent_on=date(2026, 9, 12),
            ),
            Expense(
                category=ExpenseCategory.CONNECTIVITY,
                amount=Decimal("1500"),
                spent_on=date(2026, 9, 20),
            ),
        ]
    )
    await session.flush()
    return {"garden": garden_machine, "dynamo": dynamo_machine}


def _revenue(machine: Machine, day: date, channel: PaymentChannel, amount: str) -> DailyRevenue:
    return DailyRevenue(
        machine_id=machine.id,
        day=day,
        channel=channel,
        amount=Decimal(amount),
        source=RevenueSource.MANUAL,
    )


async def test_business_month(session: AsyncSession, business: dict[str, Machine]) -> None:
    pnl = await FinanceService(session).monthly_pnl(date(2026, 9, 15))

    assert pnl.total_revenue == Decimal("90000")
    # 20% of 60 000 in the garden plus fixed 12 000 at Dynamo
    assert pnl.rent == Decimal("24000")
    assert pnl.total_expenses == Decimal("29500")
    assert pnl.net_profit == Decimal("60500")


async def test_machine_month_gets_a_share_of_common_expenses(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    service = FinanceService(session)
    pnl = await service.monthly_pnl(date(2026, 9, 1), business["garden"].id)

    assert pnl.total_revenue == Decimal("60000")
    assert pnl.expenses == {
        ExpenseCategory.RENT: Decimal("12000.00"),
        ExpenseCategory.REPAIR: Decimal("4000"),
        # 1 500 for SIM cards isn't tied to a machine: half of it lands here
        ExpenseCategory.CONNECTIVITY: Decimal("750.00"),
    }
    assert pnl.net_profit == Decimal("43250.00")


async def test_statement_for_part_of_a_month(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    statement = await FinanceService(session).statement(date(2026, 9, 1), date(2026, 9, 5))

    # Only the card sales of the 5th; coins were taken on the 6th.
    assert statement.total_revenue == Decimal("80000")
    # Fixed 12 000 for 5 of 30 days, plus 20% of the garden's 50 000.
    assert statement.rent == Decimal("2000.00") + Decimal("10000.00")
    assert statement.cost_of_sales == statement.rent


async def test_all_time_starts_at_first_launch(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    service = FinanceService(session)
    assert await service.first_day() == date(2026, 6, 10)
    assert await service.first_day(business["dynamo"].id) == date(2026, 7, 1)


async def test_empty_month_still_charges_fixed_rent(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    pnl = await FinanceService(session).monthly_pnl(date(2026, 8, 1))
    assert pnl.total_revenue == 0
    assert pnl.net_profit == Decimal("-12000")


async def test_payback_counts_from_launch(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    status = await FinanceService(session).machine_payback(
        business["dynamo"].id, today=date(2026, 9, 30)
    )
    # July and August: rent only; September: 30 000 revenue minus 12 000 rent
    # and half of the common 1 500 expense.
    assert status.earned == Decimal("-6750.00")
    assert status.reached_in is None


async def test_unknown_machine(session: AsyncSession) -> None:
    with pytest.raises(MachineNotFoundError):
        await FinanceService(session).monthly_pnl(date(2026, 9, 1), machine_id=999)


async def test_snapshot_gives_the_same_numbers(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    live = FinanceService(session)
    snapshot = await FinanceService.snapshot(session)
    periods = [
        (date(2026, 9, 1), date(2026, 9, 30)),
        (date(2026, 9, 10), date(2026, 10, 20)),
        (date(2024, 1, 1), date(2026, 12, 31)),
    ]
    for machine_id in [None, *(m.id for m in business.values())]:
        for start, end in periods:
            assert await snapshot.statement(start, end, machine_id) == await live.statement(
                start, end, machine_id
            )
        assert await snapshot.first_day(machine_id) == await live.first_day(machine_id)
    today = date(2026, 10, 21)
    assert await snapshot.business_payback(today) == await live.business_payback(today)
