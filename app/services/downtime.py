from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import ConnectionEvent, Machine

# Losing the connection for a few hours is routine; after this the machine counts as down.
OFFLINE_GRACE = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Downtime:
    machine: Machine
    since: datetime
    broken: bool
    days: int


class DowntimeService:
    """Says which machines are standing idle and for how long.

    A machine is down when an inspection marked it broken, or when it has been offline
    for more than a day.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def all_down(self) -> list[Downtime]:
        machines = await self.session.scalars(
            select(Machine).where(Machine.is_active).order_by(Machine.name)
        )
        result = []
        for machine in machines:
            if downtime := await self.for_machine(machine):
                result.append(downtime)
        return sorted(result, key=lambda d: d.since)

    async def for_machine(self, machine: Machine) -> Downtime | None:
        now = self.clock.now()
        since: datetime | None = machine.broken_since
        if since is None and machine.is_online is False:
            since = await self._offline_since(machine)
            if since is None or now - since < OFFLINE_GRACE:
                return None
        if since is None:
            return None
        started = since.astimezone(self.clock.tz).date()
        return Downtime(
            machine=machine,
            since=since,
            broken=machine.is_broken,
            days=max((self.clock.today() - started).days, 1),
        )

    async def _offline_since(self, machine: Machine) -> datetime | None:
        last_online = await self.session.scalar(
            select(func.max(ConnectionEvent.occurred_at)).where(
                ConnectionEvent.machine_id == machine.id, ConnectionEvent.online
            )
        )
        stmt = select(func.min(ConnectionEvent.occurred_at)).where(
            ConnectionEvent.machine_id == machine.id, ConnectionEvent.online.is_(False)
        )
        if last_online is not None:
            stmt = stmt.where(ConnectionEvent.occurred_at > last_online)
        return await self.session.scalar(stmt)
