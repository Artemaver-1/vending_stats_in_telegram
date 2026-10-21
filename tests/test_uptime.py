from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

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
