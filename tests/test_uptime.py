from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.uptime import Transition, daily_uptime

TZ = ZoneInfo("Asia/Yekaterinburg")


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=TZ)


def test_offline_for_half_a_day() -> None:
    transitions = [Transition(at(10, 12), online=False), Transition(at(11, 0), online=True)]
    uptime = daily_uptime(transitions, date(2026, 10, 9), date(2026, 10, 11), tz=TZ, now=at(12, 0))
    assert uptime == {date(2026, 10, 9): 1.0, date(2026, 10, 10): 0.5, date(2026, 10, 11): 1.0}


def test_state_before_first_event_is_inferred() -> None:
    # The first thing we ever saw was the machine coming back online,
    # so it must have been offline before that.
    uptime = daily_uptime(
        [Transition(at(10, 6), online=True)],
        date(2026, 10, 9),
        date(2026, 10, 10),
        tz=TZ,
        now=at(11, 0),
    )
    assert uptime[date(2026, 10, 9)] == 0.0
    assert uptime[date(2026, 10, 10)] == pytest.approx(0.75)


def test_today_is_measured_up_to_now_and_future_is_unknown() -> None:
    uptime = daily_uptime(
        [Transition(at(1, 0), online=True), Transition(at(10, 3), online=False)],
        date(2026, 10, 10),
        date(2026, 10, 11),
        tz=TZ,
        now=at(10, 6),
    )
    assert uptime[date(2026, 10, 10)] == pytest.approx(0.5)
    assert uptime[date(2026, 10, 11)] is None


def test_no_events_falls_back_to_current_status() -> None:
    days = (date(2026, 10, 9), date(2026, 10, 10))
    online = daily_uptime([], *days, tz=TZ, now=at(11, 0), current_online=True)
    unknown = daily_uptime([], *days, tz=TZ, now=at(11, 0))
    assert set(online.values()) == {1.0}
    assert set(unknown.values()) == {None}


def test_duplicate_events_do_not_break_intervals() -> None:
    transitions = [
        Transition(at(10, 0), online=False),
        Transition(at(10, 6), online=False),
        Transition(at(10, 12), online=True),
    ]
    uptime = daily_uptime(transitions, date(2026, 10, 10), date(2026, 10, 10), tz=TZ, now=at(11, 0))
    assert uptime[date(2026, 10, 10)] == pytest.approx(0.5)


async def test_days_before_telemetry_are_unknown(session: AsyncSession) -> None:
    from decimal import Decimal

    from app.db.models import ConnectionEvent, Machine
    from app.services.uptime import UptimeService
    from tests.helpers import FixedClock

    machine = Machine(name="Динамо", purchase_cost=Decimal(1), launched_on=date(2024, 7, 1))
    session.add(machine)
    await session.flush()
    session.add(
        ConnectionEvent(id="e1", machine_id=machine.id, occurred_at=at(10, 12), online=False)
    )
    await session.flush()

    service = UptimeService(session, FixedClock(at(20, 12)))
    months = await service.monthly(machine, 2026)
    # Nothing is known before the first SmartVend event in October.
    assert all(months[date(2026, m, 1)] is None for m in range(1, 10))
    assert months[date(2026, 10, 1)] is not None
    assert months[date(2026, 12, 1)] is None


def test_estimate_from_payments() -> None:
    from app.domain.uptime import estimate_from_payments

    d = lambda n: date(2024, 7, n)  # noqa: E731
    paid = {d(3), d(4), d(6), d(10)}
    days = estimate_from_payments(paid, d(1), d(12))
    # Before the first payment the machine wasn't running yet.
    assert [days[d(1)], days[d(2)]] == [False, False]
    # A single empty day between payments is just a slow day.
    assert days[d(5)] is True
    # Three empty days in a row mean it was off; so does the tail after the last payment.
    assert [days[d(7)], days[d(8)], days[d(9)]] == [False, False, False]
    assert [days[d(11)], days[d(12)]] == [False, False]
