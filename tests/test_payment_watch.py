from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Machine, TelemetrySale
from app.domain.enums import PaymentChannel
from app.services.payment_watch import PaymentWatch, allowed_hits
from tests.helpers import TZ, FixedClock

NOW = datetime(2026, 10, 21, 12, tzinfo=TZ)


async def add_sales(
    session: AsyncSession, machine: Machine, pattern: list[str], end: datetime
) -> None:
    for i, kind in enumerate(reversed(pattern)):
        session.add(
            TelemetrySale(
                id=f"{machine.id}-{end.timestamp()}-{i}",
                machine_id=machine.id,
                sold_at=end - timedelta(minutes=10 * i),
                bill=Decimal(10 if kind == "bill" else 0),
                coin=Decimal(10 if kind == "coin" else 0),
                card=Decimal(10 if kind == "card" else 0),
            )
        )
    await session.flush()


async def machine(session: AsyncSession) -> Machine:
    item = Machine(name="Пушкина", purchase_cost=Decimal(1))
    session.add(item)
    await session.flush()
    return item


def test_one_stray_payment_is_tolerated() -> None:
    assert [allowed_hits(n) for n in (10, 99, 100, 250)] == [1, 1, 1, 2]


async def test_two_quiet_days_raise_an_alert_until_payments_return(
    session: AsyncSession,
) -> None:
    pushkina = await machine(session)
    # Coins were in use a week ago; over the last two days only cards and bills, plus one
    # coin that slipped through.
    await add_sales(session, pushkina, ["coin", "card", "bill"] * 10, NOW - timedelta(days=7))
    await add_sales(session, pushkina, ["card", "bill"] * 12 + ["coin"], NOW)

    watch = PaymentWatch(session, FixedClock(NOW))
    first = await watch.run()
    assert [a.channel for a in first.raised] == [PaymentChannel.COIN]
    assert (await watch.run()).raised == []

    await add_sales(session, pushkina, ["coin", "card"] * 3, NOW + timedelta(hours=5))
    later = PaymentWatch(session, FixedClock(NOW + timedelta(hours=5)))
    assert [a.channel for a in (await later.run()).cleared] == [PaymentChannel.COIN]
    assert await later.open_alerts() == []


async def test_unused_method_and_idle_machine_are_left_alone(session: AsyncSession) -> None:
    pushkina = await machine(session)
    # Nobody ever pays with bills here, so their absence means nothing.
    await add_sales(session, pushkina, ["card", "coin"] * 20, NOW)
    assert (await PaymentWatch(session, FixedClock(NOW)).run()).raised == []

    # Few sales in two days is a quiet machine, not a broken acceptor.
    other = Machine(name="Динамо", purchase_cost=Decimal(1))
    session.add(other)
    await session.flush()
    await add_sales(session, other, ["coin", "card"] * 10, NOW - timedelta(days=5))
    await add_sales(session, other, ["card"] * 5, NOW)
    assert (await PaymentWatch(session, FixedClock(NOW)).run()).raised == []


async def test_late_smartvend_data_still_counts(session: AsyncSession) -> None:
    pushkina = await machine(session)
    # The last sales SmartVend delivered are three days old and had no coins.
    stopped = NOW - timedelta(days=3)
    await add_sales(session, pushkina, ["coin", "card", "bill"] * 10, stopped - timedelta(days=7))
    await add_sales(session, pushkina, ["card", "bill"] * 15, stopped)
    raised = (await PaymentWatch(session, FixedClock(NOW)).run()).raised
    assert [a.channel for a in raised] == [PaymentChannel.COIN]

    # Ten days without any sales is downtime, not a payment problem.
    much_later = PaymentWatch(session, FixedClock(NOW + timedelta(days=8)))
    assert (await much_later.run()).raised == []
