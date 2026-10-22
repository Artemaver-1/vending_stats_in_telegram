from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyRevenue, Encashment, Expense, Machine, Payout
from app.domain.enums import (
    EncashmentStatus,
    ExpenseCategory,
    PaidFrom,
    PaymentChannel,
    RevenueSource,
)
from app.services.treasury import TreasuryService
from tests.helpers import TZ, FixedClock


async def test_monthly_flows(session: AsyncSession) -> None:
    machine = Machine(name="Пушкина", purchase_cost=Decimal(1))
    session.add(machine)
    await session.flush()
    session.add_all(
        [
            DailyRevenue(
                machine_id=machine.id,
                day=date(2026, 9, 30),
                channel=PaymentChannel.CARD,
                source=RevenueSource.VENDISTA,
                amount=Decimal("700"),
            ),
            DailyRevenue(
                machine_id=machine.id,
                day=date(2026, 10, 1),
                channel=PaymentChannel.CARD,
                source=RevenueSource.VENDISTA,
                amount=Decimal("300"),
            ),
            # Coins never reach the bank by themselves, only through a deposit.
            DailyRevenue(
                machine_id=machine.id,
                day=date(2026, 10, 1),
                channel=PaymentChannel.COIN,
                source=RevenueSource.TELEMETRY,
                amount=Decimal("90"),
            ),
            Encashment(
                machine_id=machine.id,
                status=EncashmentStatus.DEPOSITED,
                took_bills=True,
                took_coins=True,
                collected_at=datetime(2026, 10, 2, 12, tzinfo=TZ),
                deposited=Decimal("500"),
                deposited_on=date(2026, 10, 3),
            ),
            Expense(
                category=ExpenseCategory.PARTS,
                amount=Decimal("200"),
                spent_on=date(2026, 10, 5),
                paid_from=PaidFrom.BANK,
            ),
            Expense(
                category=ExpenseCategory.PARTS,
                amount=Decimal("50"),
                spent_on=date(2026, 10, 5),
                paid_from=PaidFrom.CASH,
            ),
            Payout(paid_on=date(2026, 9, 15), amount=Decimal("100"), recipient="Артём"),
        ]
    )
    await session.flush()

    clock = FixedClock(datetime(2026, 10, 21, 12, tzinfo=TZ))
    flows = await TreasuryService(session, clock).months(count=3)
    assert [f.month for f in flows] == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
    august, september, october = flows
    assert august.bank_change == 0
    assert (september.card_in, september.paid_out, september.bank_change) == (700, 100, 600)
    assert (october.card_in, october.deposited, october.spent_from_bank) == (300, 500, 200)
    assert october.bank_change == 600
