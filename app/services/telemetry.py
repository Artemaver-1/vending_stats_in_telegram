import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import batched
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import ConnectionEvent, Location, Machine
from app.domain.enums import PaymentChannel, RevenueSource
from app.integrations.smartvend import SmartVendClient
from app.repositories import MachineRepository
from app.repositories.telemetry import (
    ConnectionEventRepository,
    DailyRevenueWriter,
    SyncStateRepository,
    TelemetrySaleRepository,
)

logger = logging.getLogger(__name__)

UPSERT_CHUNK = 1000
ONLINE_CODES = {"controller_online": True, "controller_offline": False}


def day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


class _TelemetrySync:
    def __init__(self, session: AsyncSession, client: SmartVendClient, clock: Clock) -> None:
        self.session = session
        self.client = client
        self.clock = clock
        self.machines = MachineRepository(session)
        self.states = SyncStateRepository(session)

    async def _machines_by_device(self) -> dict[str, Machine]:
        return {
            m.telemetry_device_id: m for m in await self.machines.list() if m.telemetry_device_id
        }


class ControllerRegistry(_TelemetrySync):
    """Mirrors SmartVend controllers into machines and refreshes their online flag."""

    def __init__(
        self,
        session: AsyncSession,
        client: SmartVendClient,
        clock: Clock,
        *,
        default_cost: Decimal,
    ) -> None:
        super().__init__(session, client, clock)
        self.default_cost = default_cost

    async def run(self) -> list[Machine]:
        known = await self._machines_by_device()
        checked_at = self.clock.now()
        created: list[Machine] = []

        for controller in await self.client.controllers():
            machine = known.get(controller.id)
            if machine is None:
                machine = Machine(
                    name=controller.name,
                    telemetry_device_id=controller.id,
                    purchase_cost=self.default_cost,
                    location_id=(await self._location_for(controller.name, controller.address)).id,
                )
                self.session.add(machine)
                created.append(machine)
                logger.info("Registered new machine %r from SmartVend", controller.name)
            machine.is_online = controller.online
            machine.status_checked_at = checked_at

        await self.session.flush()
        return created

    async def _location_for(self, name: str, address: str | None) -> Location:
        location = await self.session.scalar(select(Location).where(Location.name == name))
        if location is None:
            location = Location(name=name, address=address)
            self.session.add(location)
            await self.session.flush()
        return location


@dataclass(slots=True)
class _DayTotal:
    amount: Decimal = field(default_factory=Decimal)
    count: int = 0


@dataclass(frozen=True, slots=True)
class SalesSyncResult:
    first_day: date
    last_day: date
    fetched: int
    skipped: int


class SalesSync(_TelemetrySync):
    """Pulls sales from SmartVend and rebuilds daily revenue for the affected days.

    Every run re-reads a few days before the stored cursor: a controller that was offline
    uploads its sales later, stamped with the time they actually happened.
    """

    source = "smartvend_sales"

    def __init__(
        self,
        session: AsyncSession,
        client: SmartVendClient,
        clock: Clock,
        *,
        history_start: date,
        lookback_days: int,
    ) -> None:
        super().__init__(session, client, clock)
        self.history_start = history_start
        self.lookback = timedelta(days=lookback_days)
        self.sales = TelemetrySaleRepository(session)
        self.revenue = DailyRevenueWriter(session)

    async def run(self) -> SalesSyncResult:
        state = await self.states.get(self.source)
        tz, today = self.clock.tz, self.clock.today()
        first_day = (
            self.history_start
            if state.synced_through is None
            else max(state.synced_through - self.lookback, self.history_start)
        )

        machines = await self._machines_by_device()
        rows: list[dict[str, Any]] = []
        skipped = 0
        async for sale in self.client.sales(day_start(first_day, tz), self.clock.now()):
            machine = machines.get(sale.controller_id)
            if machine is None:
                skipped += 1
                continue
            rows.append(
                {
                    "id": sale.id,
                    "machine_id": machine.id,
                    "sold_at": sale.sold_at,
                    "bill": sale.bill,
                    "coin": sale.coin,
                    "card": sale.card,
                    "canceled": sale.canceled or sale.hidden,
                }
            )
        for chunk in batched(rows, UPSERT_CHUNK):
            await self.sales.upsert_many(chunk)

        covered = {m.id: m.vendista_covered_through for m in machines.values()}
        await self._rebuild_daily_revenue(first_day, today, covered)
        await self._fill_launch_dates(machines.values())

        state.synced_through = today
        state.last_error = None
        await self.session.flush()
        if skipped:
            logger.warning("Skipped %d sales from controllers unknown to the database", skipped)
        return SalesSyncResult(first_day, today, fetched=len(rows), skipped=skipped)

    async def _rebuild_daily_revenue(
        self, first: date, last: date, vendista_covered: dict[int, date | None]
    ) -> None:
        tz = self.clock.tz
        sales = await self.sales.between(day_start(first, tz), day_start(last + timedelta(1), tz))

        totals: dict[tuple[int, date, PaymentChannel], _DayTotal] = defaultdict(_DayTotal)
        for sale in sales:
            day = sale.sold_at.astimezone(tz).date()
            for channel, amount in (
                (PaymentChannel.BILL, sale.bill),
                (PaymentChannel.COIN, sale.coin),
                (PaymentChannel.CARD, sale.card),
            ):
                covered_through = vendista_covered.get(sale.machine_id)
                if channel is PaymentChannel.CARD and covered_through and day <= covered_through:
                    continue
                if amount > 0:
                    total = totals[(sale.machine_id, day, channel)]
                    total.amount += amount
                    total.count += 1

        rows = [
            {
                "machine_id": machine_id,
                "day": day,
                "channel": channel,
                "amount": total.amount,
                "sales_count": total.count,
                "source": RevenueSource.TELEMETRY,
            }
            for (machine_id, day, channel), total in totals.items()
        ]
        await self.revenue.replace_days(first, last, RevenueSource.TELEMETRY, rows)

    async def _fill_launch_dates(self, machines: Iterable[Machine]) -> None:
        for machine in machines:
            if machine.launched_on is None:
                first_sale = await self.sales.first_sale_at(machine.id)
                if first_sale is not None:
                    machine.launched_on = first_sale.astimezone(self.clock.tz).date()


class ConnectivitySync(_TelemetrySync):
    """Stores online/offline transitions reported by SmartVend."""

    source = "smartvend_events"

    def __init__(
        self,
        session: AsyncSession,
        client: SmartVendClient,
        clock: Clock,
        *,
        history_start: date,
    ) -> None:
        super().__init__(session, client, clock)
        self.history_start = history_start
        self.events = ConnectionEventRepository(session)

    async def run(self) -> int:
        state = await self.states.get(self.source)
        first_day = (
            self.history_start
            if state.synced_through is None
            else max(state.synced_through - timedelta(days=1), self.history_start)
        )

        machines = await self._machines_by_device()
        rows = []
        async for event in self.client.events(
            day_start(first_day, self.clock.tz), self.clock.now()
        ):
            machine = machines.get(event.controller_id)
            if machine is None or event.code not in ONLINE_CODES:
                continue
            rows.append(
                {
                    "id": event.id,
                    "machine_id": machine.id,
                    "occurred_at": event.occurred_at,
                    "online": ONLINE_CODES[event.code],
                    # Nobody needs alerts about the history imported on the first run.
                    "notified": state.synced_through is None,
                }
            )
        for chunk in batched(rows, UPSERT_CHUNK):
            await self.events.insert_new(chunk)

        state.synced_through = self.clock.today()
        state.last_error = None
        await self.session.flush()
        return len(rows)

    async def take_unnotified(self, max_age: timedelta) -> Sequence[ConnectionEvent]:
        """Returns fresh transitions to alert about and marks everything as handled.

        The flag is only persisted when the caller's transaction commits, so if sending
        the alert fails the events stay pending for the next run.
        """
        pending = await self.events.pending_notifications(since=self.clock.now() - max_age)
        for event in pending:
            await self.session.refresh(event, ["machine"])
        await self.events.mark_all_notified()
        return pending
