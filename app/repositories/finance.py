from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select

from app.db.models import DailyRevenue, Expense, RentContract
from app.domain.enums import ExpenseCategory, PaymentChannel
from app.repositories.base import Repository


class RevenueRepository(Repository[DailyRevenue]):
    model = DailyRevenue

    async def totals_by_channel(
        self, start: date, end: date, machine_ids: Collection[int] | None = None
    ) -> dict[PaymentChannel, Decimal]:
        """Sums revenue for days in [start, end)."""
        stmt = (
            select(DailyRevenue.channel, func.sum(DailyRevenue.amount))
            .where(DailyRevenue.day >= start, DailyRevenue.day < end)
            .group_by(DailyRevenue.channel)
        )
        if machine_ids is not None:
            stmt = stmt.where(DailyRevenue.machine_id.in_(machine_ids))
        rows = await self.session.execute(stmt)
        return {channel: Decimal(total) for channel, total in rows}

    async def first_day(self) -> date | None:
        return await self.session.scalar(select(func.min(DailyRevenue.day)))


class ExpenseRepository(Repository[Expense]):
    model = Expense

    async def totals_by_category(
        self,
        start: date,
        end: date,
        machine_ids: Collection[int] | None = None,
        *,
        include_shared: bool = True,
    ) -> dict[ExpenseCategory, Decimal]:
        stmt = (
            select(Expense.category, func.sum(Expense.amount))
            .where(Expense.spent_on >= start, Expense.spent_on < end)
            .group_by(Expense.category)
        )
        if machine_ids is not None:
            machine_filter = Expense.machine_id.in_(machine_ids)
            stmt = stmt.where(
                or_(machine_filter, Expense.machine_id.is_(None))
                if include_shared
                else machine_filter
            )
        rows = await self.session.execute(stmt)
        return {category: Decimal(total) for category, total in rows}

    async def recent(self, limit: int = 10) -> Sequence[Expense]:
        result = await self.session.scalars(
            select(Expense).order_by(Expense.spent_on.desc(), Expense.id.desc()).limit(limit)
        )
        return result.all()


class RentContractRepository(Repository[RentContract]):
    model = RentContract

    async def active_between(
        self, start: date, end: date, location_ids: Collection[int] | None = None
    ) -> Sequence[RentContract]:
        """Contracts that were in force at any point during [start, end)."""
        stmt = select(RentContract).where(
            RentContract.valid_from < end,
            or_(RentContract.valid_to.is_(None), RentContract.valid_to >= start),
        )
        if location_ids is not None:
            stmt = stmt.where(RentContract.location_id.in_(location_ids))
        result = await self.session.scalars(stmt)
        return result.all()
