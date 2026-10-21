from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectionEvent, DailyRevenue, SyncState, TelemetrySale
from app.domain.enums import RevenueSource
from app.repositories.base import Repository


class TelemetrySaleRepository(Repository[TelemetrySale]):
    model = TelemetrySale

    async def upsert_many(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = insert(TelemetrySale).values(list(rows))
        stmt = stmt.on_conflict_do_update(
            index_elements=[TelemetrySale.id],
            set_={"canceled": stmt.excluded.canceled, "sold_at": stmt.excluded.sold_at},
        )
        await self.session.execute(stmt)

    async def between(self, start: datetime, end: datetime) -> Sequence[TelemetrySale]:
        result = await self.session.scalars(
            select(TelemetrySale).where(
                TelemetrySale.sold_at >= start,
                TelemetrySale.sold_at < end,
                TelemetrySale.canceled.is_(False),
            )
        )
        return result.all()

    async def first_sale_at(self, machine_id: int) -> datetime | None:
        result = await self.session.scalars(
            select(TelemetrySale.sold_at)
            .where(TelemetrySale.machine_id == machine_id)
            .order_by(TelemetrySale.sold_at)
            .limit(1)
        )
        return result.first()


class DailyRevenueWriter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_days(
        self,
        first: date,
        last: date,
        source: RevenueSource,
        rows: Sequence[dict[str, Any]],
        *,
        machine_id: int | None = None,
    ) -> None:
        """Atomically swaps the revenue a source reported for [first, last] with fresh rows."""
        stmt = delete(DailyRevenue).where(
            DailyRevenue.source == source,
            DailyRevenue.day >= first,
            DailyRevenue.day <= last,
        )
        if machine_id is not None:
            stmt = stmt.where(DailyRevenue.machine_id == machine_id)
        await self.session.execute(stmt)
        if rows:
            await self.session.execute(insert(DailyRevenue).values(list(rows)))


class ConnectionEventRepository(Repository[ConnectionEvent]):
    model = ConnectionEvent

    async def insert_new(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = insert(ConnectionEvent).values(list(rows))
        await self.session.execute(stmt.on_conflict_do_nothing(index_elements=[ConnectionEvent.id]))

    async def for_machine(
        self, machine_id: int, until: datetime | None = None
    ) -> Sequence[ConnectionEvent]:
        stmt = (
            select(ConnectionEvent)
            .where(ConnectionEvent.machine_id == machine_id)
            .order_by(ConnectionEvent.occurred_at)
        )
        if until is not None:
            stmt = stmt.where(ConnectionEvent.occurred_at < until)
        result = await self.session.scalars(stmt)
        return result.all()

    async def pending_notifications(self, since: datetime) -> Sequence[ConnectionEvent]:
        result = await self.session.scalars(
            select(ConnectionEvent)
            .where(ConnectionEvent.notified.is_(False), ConnectionEvent.occurred_at >= since)
            .order_by(ConnectionEvent.occurred_at)
        )
        return result.all()

    async def mark_all_notified(self) -> None:
        await self.session.execute(
            update(ConnectionEvent).where(ConnectionEvent.notified.is_(False)).values(notified=True)
        )


class SyncStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, source: str) -> SyncState:
        state = await self.session.get(SyncState, source)
        if state is None:
            state = SyncState(source=source)
            self.session.add(state)
        return state
