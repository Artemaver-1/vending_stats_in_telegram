from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class Transition:
    at: datetime
    online: bool


def daily_uptime(
    transitions: Sequence[Transition],
    first: date,
    last: date,
    *,
    tz: ZoneInfo,
    now: datetime,
    current_online: bool | None = None,
) -> dict[date, float | None]:
    """Share of every day in [first, last] the machine was online, in the business timezone.

    State before the earliest known transition is assumed to be the opposite of it;
    with no transitions at all `current_online` is used for the whole range.
    Days that haven't started yet map to None, today is measured up to `now`.
    """
    events = sorted(transitions, key=lambda t: t.at)
    range_start = _day_start(first, tz)
    range_end = min(_day_start(last + timedelta(days=1), tz), now)

    if events:
        state = not events[0].online
    elif current_online is not None:
        state = current_online
    else:
        return {day: None for day in _days(first, last)}

    for event in events:
        if event.at > range_start:
            break
        state = event.online

    segments: list[tuple[datetime, datetime]] = []
    cursor = range_start
    for event in events:
        if event.at <= range_start:
            continue
        if event.at >= range_end:
            break
        if event.online != state:
            if state:
                segments.append((cursor, event.at))
            cursor, state = event.at, event.online
    if state and cursor < range_end:
        segments.append((cursor, range_end))

    result: dict[date, float | None] = {}
    for day in _days(first, last):
        start = _day_start(day, tz)
        end = min(_day_start(day + timedelta(days=1), tz), now)
        if end <= start:
            result[day] = None
            continue
        online = sum(
            (min(seg_end, end) - max(seg_start, start)).total_seconds()
            for seg_start, seg_end in segments
            if seg_start < end and seg_end > start
        )
        result[day] = online / (end - start).total_seconds()
    return result


def _day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]
