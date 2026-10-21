from collections.abc import Iterator
from datetime import date


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def previous_month(day: date) -> date:
    if day.month == 1:
        return date(day.year - 1, 12, 1)
    return date(day.year, day.month - 1, 1)


def iter_months(first: date, last: date) -> Iterator[date]:
    """Yields the first day of every month from `first` to `last`, both inclusive."""
    current, stop = month_start(first), month_start(last)
    while current <= stop:
        yield current
        current = next_month(current)
