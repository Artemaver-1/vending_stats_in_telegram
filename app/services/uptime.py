from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import DailyRevenue, EstimatedUptime, Machine
from app.domain.enums import PaymentChannel, RevenueSource
from app.domain.uptime import Transition, daily_uptime, estimate_from_payments
from app.repositories.telemetry import ConnectionEventRepository, TelemetrySaleRepository


class UptimeService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.events = ConnectionEventRepository(session)
        self.sales = TelemetrySaleRepository(session)
        self.clock = clock

    async def daily(self, machine: Machine, first: date, last: date) -> dict[date, float | None]:
        """Share of every day the machine was online; None where nothing is known."""
        events = await self.events.for_machine(machine.id)
        uptime = daily_uptime(
            [Transition(at=e.occurred_at, online=e.online) for e in events],
            first,
            last,
            tz=self.clock.tz,
            now=self.clock.now(),
            current_online=machine.is_online,
        )
        # Before SmartVend reported anything, fall back to the estimate made from Vendista
        # payments; where there is none either, the day stays unknown rather than "offline".
        first_event = events[0].occurred_at.astimezone(self.clock.tz).date() if events else None
        known_from = await self._telemetry_start(machine, first_event)
        estimated = await self._estimated(machine.id, first, last)
        for day in uptime:
            if known_from is None or day < known_from:
                worked = estimated.get(day)
                uptime[day] = None if worked is None else float(worked)
        return uptime

    async def telemetry_start(self, machine: Machine) -> date | None:
        """First day SmartVend knew anything about the machine's connection."""
        events = await self.events.for_machine(machine.id)
        first_event = events[0].occurred_at.astimezone(self.clock.tz).date() if events else None
        return await self._telemetry_start(machine, first_event)

    async def _estimated(self, machine_id: int, first: date, last: date) -> dict[date, bool]:
        rows = await self.session.execute(
            select(EstimatedUptime.day, EstimatedUptime.worked).where(
                EstimatedUptime.machine_id == machine_id,
                EstimatedUptime.day >= first,
                EstimatedUptime.day <= last,
            )
        )
        return {day: worked for day, worked in rows}

    async def monthly(self, machine: Machine, year: int) -> dict[date, float | None]:
        """Average daily uptime for each month of the year; None for months with no data."""
        today = self.clock.today()
        months: dict[date, float | None] = {date(year, m, 1): None for m in range(1, 13)}
        if date(year, 1, 1) > today:
            return months
        days = await self.daily(machine, date(year, 1, 1), min(date(year, 12, 31), today))
        known: dict[date, list[float]] = defaultdict(list)
        for day, share in days.items():
            if share is not None:
                known[day.replace(day=1)].append(share)
        return {month: (sum(v) / len(v) if (v := known.get(month)) else None) for month in months}

    async def _telemetry_start(self, machine: Machine, first_event: date | None) -> date | None:
        candidates = [first_event] if first_event else []
        if first_sale := await self.sales.first_sale_at(machine.id):
            candidates.append(first_sale.astimezone(self.clock.tz).date())
        start = min(candidates) if candidates else None
        if machine.launched_on is not None and start is not None:
            start = max(start, machine.launched_on)
        return start


class UptimeEstimator:
    """Fills `estimated_uptime` from Vendista card payments for the days between a
    machine's launch and the first connection data from SmartVend."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.uptime = UptimeService(session, clock)

    async def rebuild(self, machine: Machine) -> int:
        payment_days = set(
            await self.session.scalars(
                select(DailyRevenue.day).where(
                    DailyRevenue.machine_id == machine.id,
                    DailyRevenue.channel == PaymentChannel.CARD,
                    DailyRevenue.source == RevenueSource.VENDISTA,
                    DailyRevenue.amount > 0,
                )
            )
        )
        await self.session.execute(
            delete(EstimatedUptime).where(EstimatedUptime.machine_id == machine.id)
        )
        if not payment_days:
            return 0
        first = machine.launched_on or min(payment_days)
        telemetry_start = await self.uptime.telemetry_start(machine)
        last = (
            telemetry_start - timedelta(days=1)
            if telemetry_start
            else machine.vendista_covered_through or max(payment_days)
        )
        if first > last:
            return 0
        days = estimate_from_payments(payment_days, first, last)
        await self.session.execute(
            insert(EstimatedUptime).values(
                [{"machine_id": machine.id, "day": d, "worked": w} for d, w in days.items()]
            )
        )
        return len(days)
