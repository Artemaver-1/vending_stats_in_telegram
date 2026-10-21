from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import Machine
from app.domain.uptime import Transition, daily_uptime
from app.repositories.telemetry import ConnectionEventRepository


class UptimeService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.events = ConnectionEventRepository(session)
        self.clock = clock

    async def daily(self, machine: Machine, first: date, last: date) -> dict[date, float | None]:
        events = await self.events.for_machine(machine.id)
        uptime = daily_uptime(
            [Transition(at=e.occurred_at, online=e.online) for e in events],
            first,
            last,
            tz=self.clock.tz,
            now=self.clock.now(),
            current_online=machine.is_online,
        )
        if machine.launched_on is not None:
            for day in uptime:
                if day < machine.launched_on:
                    uptime[day] = None
        return uptime
