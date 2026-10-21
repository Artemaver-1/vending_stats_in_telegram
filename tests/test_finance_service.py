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
                category=ExpenseCategory.TRANSPORT,
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


async def test_machine_month_skips_shared_expenses(
    session: AsyncSession, business: dict[str, Machine]
) -> None:
    service = FinanceService(session)
    pnl = await service.monthly_pnl(date(2026, 9, 1), business["garden"].id)

    assert pnl.total_revenue == Decimal("60000")
    assert pnl.rent == Decimal("12000")
    assert pnl.expenses == {ExpenseCategory.REPAIR: Decimal("4000")}
    assert pnl.net_profit == Decimal("44000")


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
    assert status.earned == Decimal("-6000")
    assert status.reached_in is None


async def test_unknown_machine(session: AsyncSession) -> None:
    with pytest.raises(MachineNotFoundError):
        await FinanceService(session).monthly_pnl(date(2026, 9, 1), machine_id=999)
