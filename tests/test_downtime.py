from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectionEvent, DailyRevenue, Machine
from app.domain.enums import PaymentChannel, RevenueSource
from app.formatting import plural
from app.services.downtime import DowntimeService
from tests.helpers import TZ, FixedClock

NOW = datetime(2026, 10, 21, 12, tzinfo=TZ)


async def machine_with_takings(session: AsyncSession, **fields: object) -> Machine:
    machine = Machine(name="Динамо", purchase_cost=Decimal(1), **fields)
    session.add(machine)
    await session.flush()
    for i, amount in enumerate((600, 0, 400)):
        session.add(
            DailyRevenue(
                machine_id=machine.id,
                day=date(2026, 10, 5) + timedelta(days=i),
                channel=PaymentChannel.COIN,
                amount=Decimal(amount),
                source=RevenueSource.TELEMETRY,
            )
        )
    await session.flush()
    return machine


async def test_broken_machine_counts_days_since_it_broke(session: AsyncSession) -> None:
    machine = await machine_with_takings(session, broken_since=datetime(2026, 10, 10, 9, tzinfo=TZ))
    downtime = await DowntimeService(session, FixedClock(NOW)).for_machine(machine)

    assert downtime is not None and downtime.broken
    assert downtime.days == 11


async def test_short_connection_loss_is_not_downtime(session: AsyncSession) -> None:
    machine = await machine_with_takings(session, is_online=False)
    session.add(
        ConnectionEvent(
            id="e1", machine_id=machine.id, occurred_at=NOW - timedelta(hours=3), online=False
        )
    )
    await session.flush()
    service = DowntimeService(session, FixedClock(NOW))
    assert await service.for_machine(machine) is None

    later = DowntimeService(session, FixedClock(NOW + timedelta(days=2)))
    downtime = await later.for_machine(machine)
    assert downtime is not None and not downtime.broken and downtime.days == 2


def test_plural() -> None:
    assert [plural(n, "день", "дня", "дней") for n in (1, 2, 5, 11, 21, 104)] == [
        "день",
        "дня",
        "дней",
        "дней",
        "день",
        "дня",
    ]
