from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import ConnectionEvent, DailyRevenue, Location, Machine
from app.domain.enums import PaymentChannel
from app.integrations.smartvend import Controller, ControllerEvent, Sale, SmartVendClient
from app.services.telemetry import ConnectivitySync, ControllerRegistry, SalesSync

TZ = ZoneInfo("Asia/Yekaterinburg")


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        super().__init__(TZ)
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeSmartVend:
    def __init__(self) -> None:
        self.controller_list: list[Controller] = []
        self.sale_list: list[Sale] = []
        self.event_list: list[ControllerEvent] = []
        self.requested: list[tuple[datetime, datetime]] = []

    async def controllers(self) -> list[Controller]:
        return self.controller_list

    async def sales(self, start: datetime, end: datetime) -> AsyncIterator[Sale]:
        self.requested.append((start, end))
        for sale in self.sale_list:
            if start <= sale.sold_at <= end:
                yield sale

    async def events(self, start: datetime, end: datetime) -> AsyncIterator[ControllerEvent]:
        for event in self.event_list:
            if start <= event.occurred_at <= end:
                yield event


def controller(id_: str, name: str, status: str = "online") -> Controller:
    return Controller.model_validate(
        {"id": id_, "humanName": name, "serialNumber": "1", "connectionStatus": status}
    )


def sale(id_: str, when: datetime, *, bill: int = 0, coin: int = 0, card: int = 0) -> Sale:
    return Sale.model_validate(
        {
            "saleId": id_,
            "controllerId": "c-pushkina",
            "controllerCreatedAt": when.timestamp(),
            "bill": str(bill * 100),
            "coin": str(coin * 100),
            "digital": str(card * 100),
        }
    )


@pytest.fixture
def smartvend() -> FakeSmartVend:
    fake = FakeSmartVend()
    fake.controller_list = [
        controller("c-pushkina", "Пушкина"),
        controller("c-dynamo", "Динамо", "offline"),
    ]
    return fake


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 21, 12, tzinfo=TZ))


async def register(session: AsyncSession, smartvend: FakeSmartVend, clock: Clock) -> None:
    registry = ControllerRegistry(
        session, cast(SmartVendClient, smartvend), clock, default_cost=Decimal("320000")
    )
    await registry.run()


async def test_registry_creates_machines_once(
    session: AsyncSession, smartvend: FakeSmartVend, clock: FixedClock
) -> None:
    await register(session, smartvend, clock)
    await register(session, smartvend, clock)

    machines = (await session.scalars(select(Machine).order_by(Machine.name))).all()
    assert [(m.name, m.is_online) for m in machines] == [("Динамо", False), ("Пушкина", True)]
    assert len((await session.scalars(select(Location))).all()) == 2


async def test_sales_are_bucketed_by_local_day(
    session: AsyncSession, smartvend: FakeSmartVend, clock: FixedClock
) -> None:
    await register(session, smartvend, clock)
    # 23:30 in Chelyabinsk is still 21:30 in Moscow and 18:30 UTC: it belongs to the 19th.
    late_evening = datetime(2026, 10, 19, 23, 30, tzinfo=TZ)
    smartvend.sale_list = [
        sale("s1", late_evening, bill=10),
        sale("s2", late_evening + timedelta(hours=1), card=10),
        sale("s3", late_evening + timedelta(hours=2), coin=5, bill=5),
    ]
    sync = SalesSync(
        session,
        cast(SmartVendClient, smartvend),
        clock,
        history_start=date(2026, 10, 1),
        lookback_days=3,
    )
    await sync.run()

    rows = (await session.scalars(select(DailyRevenue).order_by(DailyRevenue.day))).all()
    by_key = {(r.day, r.channel): (r.amount, r.sales_count) for r in rows}
    assert by_key == {
        (date(2026, 10, 19), PaymentChannel.BILL): (Decimal("10"), 1),
        (date(2026, 10, 20), PaymentChannel.CARD): (Decimal("10"), 1),
        (date(2026, 10, 20), PaymentChannel.COIN): (Decimal("5"), 1),
        (date(2026, 10, 20), PaymentChannel.BILL): (Decimal("5"), 1),
    }
    pushkina = await session.scalar(select(Machine).where(Machine.name == "Пушкина"))
    assert pushkina is not None and pushkina.launched_on == date(2026, 10, 19)


async def test_rerun_picks_up_late_uploads_without_duplicates(
    session: AsyncSession, smartvend: FakeSmartVend, clock: FixedClock
) -> None:
    await register(session, smartvend, clock)
    sync = SalesSync(
        session,
        cast(SmartVendClient, smartvend),
        clock,
        history_start=date(2026, 10, 1),
        lookback_days=3,
    )
    day = datetime(2026, 10, 20, 15, tzinfo=TZ)
    smartvend.sale_list = [sale("s1", day, bill=10)]
    await sync.run()

    # The controller was offline and uploads another sale from yesterday.
    smartvend.sale_list.append(sale("s2", day + timedelta(minutes=5), bill=10))
    await sync.run()

    revenue = await session.scalar(select(DailyRevenue).where(DailyRevenue.day == day.date()))
    assert revenue is not None
    assert (revenue.amount, revenue.sales_count) == (Decimal("20"), 2)
    assert smartvend.requested[1][0] == datetime(2026, 10, 18, tzinfo=TZ)


async def test_connectivity_alerts_only_for_new_events(
    session: AsyncSession, smartvend: FakeSmartVend, clock: FixedClock
) -> None:
    await register(session, smartvend, clock)
    sync = ConnectivitySync(
        session, cast(SmartVendClient, smartvend), clock, history_start=date(2026, 10, 1)
    )

    def event(id_: str, hours_ago: int, code: str) -> ControllerEvent:
        return ControllerEvent.model_validate(
            {
                "id": id_,
                "controllerId": "c-dynamo",
                "controllerCreatedAt": (clock.now() - timedelta(hours=hours_ago)).timestamp(),
                "code": code,
            }
        )

    smartvend.event_list = [
        event("e1", 200, "controller_offline"),
        event("e2", 150, "encashment_performed"),
    ]
    assert await sync.run() == 1
    assert await sync.take_unnotified(timedelta(hours=3)) == []

    smartvend.event_list.append(event("e3", 1, "controller_online"))
    await sync.run()
    fresh = await sync.take_unnotified(timedelta(hours=3))
    assert [(e.id, e.online, e.machine.name) for e in fresh] == [("e3", True, "Динамо")]

    stored = (await session.scalars(select(ConnectionEvent))).all()
    assert len(stored) == 2
    assert datetime.now(UTC) > stored[0].occurred_at.replace(tzinfo=UTC)
