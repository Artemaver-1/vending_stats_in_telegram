from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal(0)


class DiscrepancyKind(StrEnum):
    # SmartVend booked the payments, just on other days: queued while it had no signal
    # (or the SIM wasn't paid) and uploaded when it came back, or a payment near midnight.
    SHIFTED = "shifted"
    # Vendista took payments while SmartVend saw none at all: SmartVend was off or removed.
    SMARTVEND_DOWN = "smartvend_down"
    # SmartVend saw some of the payments and never caught up on the rest.
    SMARTVEND_PARTIAL = "smartvend_partial"
    # SmartVend shows more card money than the bank received.
    SMARTVEND_EXTRA = "smartvend_extra"


@dataclass(frozen=True, slots=True)
class DayTotals:
    day: date
    vendista: Decimal
    smartvend: Decimal

    @property
    def diff(self) -> Decimal:
        return self.vendista - self.smartvend


@dataclass(slots=True)
class Discrepancy:
    kind: DiscrepancyKind
    days: list[DayTotals] = field(default_factory=list)

    @property
    def first(self) -> date:
        return self.days[0].day

    @property
    def last(self) -> date:
        return self.days[-1].day

    @property
    def vendista(self) -> Decimal:
        return sum((d.vendista for d in self.days), ZERO)

    @property
    def smartvend(self) -> Decimal:
        return sum((d.smartvend for d in self.days), ZERO)

    @property
    def balance(self) -> Decimal:
        """Card money Vendista has and SmartVend doesn't, once the episode is over."""
        return self.vendista - self.smartvend

    @property
    def moved(self) -> Decimal:
        """How much SmartVend booked on the wrong days within the episode."""
        return sum((d.diff for d in self.days if d.diff > 0), ZERO) - max(self.balance, ZERO)


def daily_series(
    vendista: Mapping[date, Decimal], smartvend: Mapping[date, Decimal], first: date, last: date
) -> list[DayTotals]:
    days = []
    day = first
    while day <= last:
        days.append(DayTotals(day, vendista.get(day, ZERO), smartvend.get(day, ZERO)))
        day += timedelta(days=1)
    return days


def find_discrepancies(days: list[DayTotals], *, settle_days: int = 7) -> list[Discrepancy]:
    """Groups day-by-day differences into episodes and tells what each one was.

    An episode opens on the first day the two sources disagree and runs while the
    running difference is not zero. It closes when the difference nets out to zero
    (SmartVend booked the same money on other days) or after `settle_days` days in a row
    agree, in which case whatever difference is left is money one side never had.
    """
    episodes: list[Discrepancy] = []
    current: list[DayTotals] = []
    balance = ZERO
    agreeing = 0

    def close() -> None:
        nonlocal current, balance, agreeing
        trimmed = current[: len(current) - agreeing] if agreeing else current
        if trimmed:
            episodes.append(Discrepancy(_classify(trimmed), trimmed))
        current, balance, agreeing = [], ZERO, 0

    for day in days:
        if not current:
            if day.diff == 0:
                continue
            current, balance, agreeing = [day], day.diff, 0
        else:
            current.append(day)
            balance += day.diff
            agreeing = agreeing + 1 if day.diff == 0 else 0
        if balance == 0 or agreeing >= settle_days:
            close()
    close()
    return episodes


def _classify(days: list[DayTotals]) -> DiscrepancyKind:
    balance = sum((d.diff for d in days), ZERO)
    if balance == 0:
        return DiscrepancyKind.SHIFTED
    if balance < 0:
        return DiscrepancyKind.SMARTVEND_EXTRA
    if all(d.smartvend == 0 for d in days):
        return DiscrepancyKind.SMARTVEND_DOWN
    return DiscrepancyKind.SMARTVEND_PARTIAL
