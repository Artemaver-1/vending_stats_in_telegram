"""In-memory copies of the finance repositories.

A dashboard asks for dozens of monthly statements, each of them several sums. With the
database across the sea every query costs a round trip, so screens that only read take
everything once (a few thousand rows) and answer the same questions from memory.
"""

from collections import defaultdict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyRevenue, Expense, Machine, RentContract
from app.domain.enums import ExpenseCategory, PaymentChannel
from app.repositories.finance import (
    ExpenseRepository,
    RentContractRepository,
    RevenueRepository,
)
from app.repositories.locations import MachineRepository


@dataclass(frozen=True, slots=True)
class _Revenue:
    day: date
    machine_id: int
    channel: PaymentChannel
    amount: Decimal


@dataclass(frozen=True, slots=True)
class _Expense:
    day: date
    machine_id: int | None
    category: ExpenseCategory
    amount: Decimal


class RevenueSnapshot(RevenueRepository):
    def __init__(self, session: AsyncSession, rows: Sequence[_Revenue]) -> None:
        super().__init__(session)
        self.rows = rows

    async def totals_by_channel(
        self, start: date, end: date, machine_ids: Collection[int] | None = None
    ) -> dict[PaymentChannel, Decimal]:
        totals: dict[PaymentChannel, Decimal] = defaultdict(Decimal)
        for row in self.rows:
            if start <= row.day < end and (machine_ids is None or row.machine_id in machine_ids):
                totals[row.channel] += row.amount
        return dict(totals)

    async def first_day(self, machine_ids: Collection[int] | None = None) -> date | None:
        days = [r.day for r in self.rows if machine_ids is None or r.machine_id in machine_ids]
        return min(days, default=None)


class ExpenseSnapshot(ExpenseRepository):
    def __init__(self, session: AsyncSession, rows: Sequence[_Expense]) -> None:
        super().__init__(session)
        self.rows = rows

    async def totals_by_category(
        self,
        start: date,
        end: date,
        machine_ids: Collection[int] | None = None,
        *,
        include_shared: bool = True,
    ) -> dict[ExpenseCategory, Decimal]:
        def wanted(row: _Expense) -> bool:
            if machine_ids is None:
                return True
            if row.machine_id is None:
                return include_shared
            return row.machine_id in machine_ids

        return self._sum(start, end, wanted)

    async def shared_totals(self, start: date, end: date) -> dict[ExpenseCategory, Decimal]:
        return self._sum(start, end, lambda row: row.machine_id is None)

    def _sum(
        self, start: date, end: date, wanted: Callable[[_Expense], bool]
    ) -> dict[ExpenseCategory, Decimal]:
        totals: dict[ExpenseCategory, Decimal] = defaultdict(Decimal)
        for row in self.rows:
            if start <= row.day < end and wanted(row):
                totals[row.category] += row.amount
        return dict(totals)


class RentContractSnapshot(RentContractRepository):
    def __init__(self, session: AsyncSession, contracts: Sequence[RentContract]) -> None:
        super().__init__(session)
        self.items = contracts

    async def active_between(
        self, start: date, end: date, location_ids: Collection[int] | None = None
    ) -> Sequence[RentContract]:
        return [
            c
            for c in self.items
            if c.valid_from < end
            and (c.valid_to is None or c.valid_to >= start)
            and (location_ids is None or c.location_id in location_ids)
        ]


class MachineSnapshot(MachineRepository):
    def __init__(self, session: AsyncSession, machines: Sequence[Machine]) -> None:
        super().__init__(session)
        self.items = sorted(machines, key=lambda m: m.name)

    async def get(self, id_: int) -> Machine | None:
        return next((m for m in self.items if m.id == id_), None)

    async def list(self) -> Sequence[Machine]:
        return self.items

    async def list_active(self) -> Sequence[Machine]:
        return [m for m in self.items if m.is_active]

    async def by_location(self, location_id: int) -> Sequence[Machine]:
        return [m for m in self.items if m.location_id == location_id and m.is_active]


@dataclass(frozen=True, slots=True)
class FinanceSnapshot:
    revenue: RevenueSnapshot
    expenses: ExpenseSnapshot
    contracts: RentContractSnapshot
    machines: MachineSnapshot

    @classmethod
    async def load(cls, session: AsyncSession) -> "FinanceSnapshot":
        revenue = await session.execute(
            select(
                DailyRevenue.day,
                DailyRevenue.machine_id,
                DailyRevenue.channel,
                func.sum(DailyRevenue.amount),
            ).group_by(DailyRevenue.day, DailyRevenue.machine_id, DailyRevenue.channel)
        )
        expenses = await session.execute(
            select(Expense.spent_on, Expense.machine_id, Expense.category, Expense.amount)
        )
        contracts = (await session.scalars(select(RentContract))).all()
        machines = (await session.scalars(select(Machine))).all()
        return cls(
            revenue=RevenueSnapshot(
                session, [_Revenue(d, m, c, Decimal(a)) for d, m, c, a in revenue]
            ),
            expenses=ExpenseSnapshot(
                session, [_Expense(d, m, c, Decimal(a)) for d, m, c, a in expenses]
            ),
            contracts=RentContractSnapshot(session, contracts),
            machines=MachineSnapshot(session, machines),
        )
