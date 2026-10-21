from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import DailyRevenue, Machine, TelemetrySale
from app.domain.enums import PaymentChannel, RevenueSource
from app.domain.reconciliation import (
    ZERO,
    DayTotals,
    Discrepancy,
    daily_series,
    find_discrepancies,
)
from app.services.telemetry import day_start
from app.services.uptime import UptimeService


@dataclass(frozen=True, slots=True)
class MonthTotals:
    month: date
    vendista: Decimal
    smartvend: Decimal

    @property
    def diff(self) -> Decimal:
        return self.vendista - self.smartvend


@dataclass(slots=True)
class ExplainedDiscrepancy:
    discrepancy: Discrepancy
    # Share of the episode's days SmartVend had no connection, when that's known.
    offline_share: float | None


@dataclass(slots=True)
class CardReconciliation:
    machine: Machine
    first: date | None = None
    last: date | None = None
    months: list[MonthTotals] = field(default_factory=list)
    discrepancies: list[ExplainedDiscrepancy] = field(default_factory=list)

    @property
    def vendista(self) -> Decimal:
        return sum((m.vendista for m in self.months), ZERO)

    @property
    def smartvend(self) -> Decimal:
        return sum((m.smartvend for m in self.months), ZERO)


class CardReconciliationService:
    """Compares card payments the bank saw (Vendista) with what SmartVend recorded.

    Only the days both could have seen are compared: from the machine's first SmartVend
    sale to the end of the latest Vendista export.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock
        self.uptime = UptimeService(session, clock)

    async def for_machine(self, machine: Machine) -> CardReconciliation:
        report = CardReconciliation(machine=machine)
        first_sale = await self.session.scalar(
            select(TelemetrySale.sold_at)
            .where(TelemetrySale.machine_id == machine.id)
            .order_by(TelemetrySale.sold_at)
            .limit(1)
        )
        if first_sale is None or machine.vendista_covered_through is None:
            return report
        first = first_sale.astimezone(self.clock.tz).date()
        last = machine.vendista_covered_through
        if first > last:
            return report

        series = daily_series(
            await self._vendista_days(machine.id, first, last),
            await self._smartvend_days(machine.id, first, last),
            first,
            last,
        )
        report.first, report.last = first, last
        report.months = _by_month(series)
        for discrepancy in find_discrepancies(series):
            uptime = await self.uptime.daily(machine, discrepancy.first, discrepancy.last)
            known = [v for v in uptime.values() if v is not None]
            offline = 1 - sum(known) / len(known) if known else None
            report.discrepancies.append(ExplainedDiscrepancy(discrepancy, offline))
        return report

    async def _vendista_days(self, machine_id: int, first: date, last: date) -> dict[date, Decimal]:
        rows = await self.session.execute(
            select(DailyRevenue.day, DailyRevenue.amount).where(
                DailyRevenue.machine_id == machine_id,
                DailyRevenue.channel == PaymentChannel.CARD,
                DailyRevenue.source == RevenueSource.VENDISTA,
                DailyRevenue.day >= first,
                DailyRevenue.day <= last,
            )
        )
        return {day: amount for day, amount in rows}

    async def _smartvend_days(
        self, machine_id: int, first: date, last: date
    ) -> dict[date, Decimal]:
        tz = self.clock.tz
        sales = await self.session.execute(
            select(TelemetrySale.sold_at, TelemetrySale.card).where(
                TelemetrySale.machine_id == machine_id,
                TelemetrySale.canceled.is_(False),
                TelemetrySale.card > 0,
                TelemetrySale.sold_at >= day_start(first, tz),
                TelemetrySale.sold_at < day_start(last + timedelta(days=1), tz),
            )
        )
        totals: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for sold_at, card in sales:
            totals[sold_at.astimezone(tz).date()] += card
        return dict(totals)


def _by_month(series: list[DayTotals]) -> list[MonthTotals]:
    vendista: dict[date, Decimal] = defaultdict(lambda: ZERO)
    smartvend: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for day in series:
        month = day.day.replace(day=1)
        vendista[month] += day.vendista
        smartvend[month] += day.smartvend
    return [MonthTotals(m, vendista[m], smartvend[m]) for m in sorted(vendista)]
