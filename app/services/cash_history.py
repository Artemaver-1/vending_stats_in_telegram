from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import Clock
from app.db.models import CashHistoryEntry, DailyRevenue, EstimatedUptime, Machine
from app.domain.enums import PaymentChannel, RevenueSource
from app.repositories.telemetry import TelemetrySaleRepository

CENT = Decimal("0.01")


class CashHistoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CashHistoryInput:
    machine_id: int
    first_day: date
    last_day: date
    coins: Decimal
    bills: Decimal
    note: str | None = None


def spread(total: Decimal, days: Sequence[date]) -> dict[date, Decimal]:
    """Splits an amount evenly over days to the kopeck; the remainder goes to the last day."""
    if not days or total == 0:
        return {}
    share = (total / len(days)).quantize(CENT, rounding=ROUND_DOWN)
    result = dict.fromkeys(days, share)
    result[days[-1]] += total - share * len(days)
    return result


class CashHistoryService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock
        self.sales = TelemetrySaleRepository(session)

    async def entries(self) -> Sequence[CashHistoryEntry]:
        result = await self.session.scalars(
            select(CashHistoryEntry)
            .options(selectinload(CashHistoryEntry.machine))
            .order_by(CashHistoryEntry.first_day)
        )
        return result.all()

    async def add(self, data: CashHistoryInput) -> CashHistoryEntry:
        machine = await self.session.get(Machine, data.machine_id)
        if machine is None:
            raise CashHistoryError("Силомер не найден")
        if data.first_day > data.last_day:
            raise CashHistoryError("Дата начала позже даты окончания")
        if data.coins < 0 or data.bills < 0 or data.coins + data.bills == 0:
            raise CashHistoryError("Укажите сумму монет или купюр")

        first_sale = await self.sales.first_sale_at(machine.id)
        if first_sale is not None:
            smartvend_from = first_sale.astimezone(self.clock.tz).date()
            if data.last_day >= smartvend_from:
                raise CashHistoryError(
                    f"С {smartvend_from:%d.%m.%Y} наличные считает SmartVend — период должен "
                    f"закончиться не позже {smartvend_from - timedelta(days=1):%d.%m.%Y}"
                )
        overlapping = await self.session.scalar(
            select(CashHistoryEntry.id).where(
                CashHistoryEntry.machine_id == machine.id,
                CashHistoryEntry.first_day <= data.last_day,
                CashHistoryEntry.last_day >= data.first_day,
            )
        )
        if overlapping is not None:
            raise CashHistoryError("Этот период уже внесён — удалите старую запись")

        entry = CashHistoryEntry(
            machine_id=machine.id,
            first_day=data.first_day,
            last_day=data.last_day,
            coins=data.coins,
            bills=data.bills,
            note=(data.note or "").strip() or None,
        )
        self.session.add(entry)
        await self.session.flush()
        await self._write_days(entry)
        return entry

    async def remove(self, entry: CashHistoryEntry) -> None:
        await self._clear_days(entry)
        await self.session.delete(entry)
        await self.session.flush()

    async def _write_days(self, entry: CashHistoryEntry) -> None:
        # Spread over the days the machine worked, as estimated from card payments; with no
        # estimate for the period every day gets an equal share.
        worked = list(
            await self.session.scalars(
                select(EstimatedUptime.day)
                .where(
                    EstimatedUptime.machine_id == entry.machine_id,
                    EstimatedUptime.day >= entry.first_day,
                    EstimatedUptime.day <= entry.last_day,
                    EstimatedUptime.worked,
                )
                .order_by(EstimatedUptime.day)
            )
        )
        days = worked or [
            entry.first_day + timedelta(days=i)
            for i in range((entry.last_day - entry.first_day).days + 1)
        ]
        rows = [
            {
                "machine_id": entry.machine_id,
                "day": day,
                "channel": channel,
                "amount": amount,
                "sales_count": 0,
                "source": RevenueSource.MANUAL,
            }
            for channel, total in (
                (PaymentChannel.COIN, entry.coins),
                (PaymentChannel.BILL, entry.bills),
            )
            for day, amount in spread(total, days).items()
        ]
        await self._clear_days(entry)
        if rows:
            await self.session.execute(insert(DailyRevenue).values(rows))

    async def _clear_days(self, entry: CashHistoryEntry) -> None:
        await self.session.execute(
            delete(DailyRevenue).where(
                DailyRevenue.machine_id == entry.machine_id,
                DailyRevenue.source == RevenueSource.MANUAL,
                DailyRevenue.channel.in_([PaymentChannel.COIN, PaymentChannel.BILL]),
                DailyRevenue.day >= entry.first_day,
                DailyRevenue.day <= entry.last_day,
            )
        )
