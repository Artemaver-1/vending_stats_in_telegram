from collections import defaultdict
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import Machine
from app.domain.uptime import Transition, daily_uptime
from app.repositories.telemetry import ConnectionEventRepository, TelemetrySaleRepository


class UptimeService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
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
        # Before the telemetry module reported anything there is no connection to speak of,
        # so those days stay unknown rather than "offline".
        first_event = events[0].occurred_at.astimezone(self.clock.tz).date() if events else None
        known_from = await self._telemetry_start(machine, first_event)
        for day in uptime:
            if known_from is None or day < known_from:
                uptime[day] = None
        return uptime

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
