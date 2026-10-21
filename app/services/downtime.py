from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import ConnectionEvent, DailyRevenue, Machine

# Losing the connection for a few hours is routine; after this the machine counts as down.
OFFLINE_GRACE = timedelta(hours=24)
# Typical takings are judged by this many days before the stop.
BASELINE_DAYS = 30


@dataclass(frozen=True, slots=True)
class Downtime:
    machine: Machine
    since: datetime
    broken: bool
    daily_loss: Decimal
    days: int

    @property
    def lost(self) -> Decimal:
        return self.daily_loss * self.days


class DowntimeService:
    """Says which machines are standing idle and what that costs.

    A machine is down when an inspection marked it broken, or when it has been offline
    for more than a day. The loss is what it used to earn on a working day in the month
    before it stopped, times the days it has been down.
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
            daily_loss=await self._daily_takings(machine, started),
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

    async def _daily_takings(self, machine: Machine, stopped: date) -> Decimal:
        rows = await self.session.execute(
            select(DailyRevenue.day, func.sum(DailyRevenue.amount))
            .where(
                DailyRevenue.machine_id == machine.id,
                DailyRevenue.day >= stopped - timedelta(days=BASELINE_DAYS),
                DailyRevenue.day < stopped,
            )
            .group_by(DailyRevenue.day)
        )
        working = [Decimal(total) for _, total in rows if total and total > 0]
        if not working:
            return Decimal(0)
        return (sum(working, Decimal(0)) / len(working)).quantize(Decimal(1))
