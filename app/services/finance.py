import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Machine, RentContract
from app.domain.enums import ExpenseCategory, RentType
from app.domain.finance import (
    ZERO,
    IncomeStatement,
    PaybackStatus,
    RentTerms,
    calculate_payback,
    to_money,
)
from app.domain.periods import iter_months, month_start, next_month
from app.repositories import (
    ExpenseRepository,
    MachineRepository,
    RentContractRepository,
    RevenueRepository,
)
from app.repositories.snapshot import FinanceSnapshot


class MachineNotFoundError(LookupError):
    pass


class FinanceService:
    """Builds income statements for any span of days, for the business or one machine.

    Rent is calculated from contract terms rather than taken from recorded payments, so
    a period's profit is right before the rent for it has been paid. A fixed rent covers
    the share of its month that falls into the period; a percentage rent applies to the
    revenue of exactly those days.

    For a single machine the location rent is split between the machines standing there
    and expenses not tied to any machine are split between all active machines.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.revenue = RevenueRepository(session)
        self.expenses = ExpenseRepository(session)
        self.contracts = RentContractRepository(session)
        self.machines = MachineRepository(session)

    @classmethod
    async def snapshot(cls, session: AsyncSession) -> "FinanceService":
        """Reads everything a statement needs in four queries and answers from memory.

        For screens that only read: a dashboard asks for dozens of monthly statements,
        and against a remote database each separate query is a round trip. Nothing
        written after this call is seen.
        """
        service = cls(session)
        books = await FinanceSnapshot.load(session)
        service.revenue, service.expenses = books.revenue, books.expenses
        service.contracts, service.machines = books.contracts, books.machines
        return service

    async def statement(
        self, start: date, end: date, machine_id: int | None = None
    ) -> IncomeStatement:
        until = end + timedelta(days=1)
        if machine_id is None:
            expenses = await self.expenses.totals_by_category(start, until)
            rent = await self._rent_between(start, end)
            revenue = await self.revenue.totals_by_channel(start, until)
        else:
            machine = await self._get_machine(machine_id)
            revenue = await self.revenue.totals_by_channel(start, until, [machine.id])
            expenses = await self.expenses.totals_by_category(
                start, until, [machine.id], include_shared=False
            )
            active = len(await self.machines.list_active()) or 1
            for category, amount in (await self.expenses.shared_totals(start, until)).items():
                expenses[category] = expenses.get(category, ZERO) + to_money(amount / active)
            rent = await self._machine_rent_share(machine, start, end)

        if rent:
            expenses[ExpenseCategory.RENT] = expenses.get(ExpenseCategory.RENT, ZERO) + rent
        return IncomeStatement(start=start, end=end, revenue=revenue, expenses=expenses)

    async def monthly_pnl(self, period: date, machine_id: int | None = None) -> IncomeStatement:
        start = month_start(period)
        return await self.statement(start, next_month(start) - timedelta(days=1), machine_id)

    async def pnl_range(
        self, first: date, last: date, machine_id: int | None = None
    ) -> list[IncomeStatement]:
        return [await self.monthly_pnl(period, machine_id) for period in iter_months(first, last)]

    async def first_day(self, machine_id: int | None = None) -> date | None:
        """Where "all time" starts: the earliest launch or the earliest recorded revenue."""
        machines = await self.machines.list()
        if machine_id is not None:
            machines = [m for m in machines if m.id == machine_id]
        candidates = [m.launched_on for m in machines if m.launched_on is not None]
        scope = [machine_id] if machine_id is not None else None
        if first_revenue := await self.revenue.first_day(scope):
            candidates.append(first_revenue)
        return min(candidates) if candidates else None

    async def machine_payback(self, machine_id: int, today: date) -> PaybackStatus:
        machine = await self._get_machine(machine_id)
        if machine.launched_on is None:
            return PaybackStatus(investment=machine.purchase_cost, earned=ZERO, reached_in=None)
        months = await self.pnl_range(machine.launched_on, today, machine.id)
        return calculate_payback(months, machine.purchase_cost)

    async def business_payback(self, today: date) -> PaybackStatus:
        machines = await self.machines.list()
        investment = sum((m.purchase_cost for m in machines), ZERO)
        launches = [m.launched_on for m in machines if m.launched_on is not None]
        if not launches:
            return PaybackStatus(investment=investment, earned=ZERO, reached_in=None)
        months = await self.pnl_range(min(launches), today)
        return calculate_payback(months, investment)

    async def rent_charge(self, contract: RentContract, period: date) -> Decimal:
        """What the contract costs for the whole month containing `period`."""
        start = month_start(period)
        return await self._contract_charge(contract, start, next_month(start) - timedelta(days=1))

    async def _get_machine(self, machine_id: int) -> Machine:
        machine = await self.machines.get(machine_id)
        if machine is None:
            raise MachineNotFoundError(machine_id)
        return machine

    async def _rent_between(
        self, start: date, end: date, location_ids: list[int] | None = None
    ) -> Decimal:
        contracts = await self.contracts.active_between(
            start, end + timedelta(days=1), location_ids
        )
        by_location: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for contract in contracts:
            for month in iter_months(start, end):
                first = max(start, month, contract.valid_from)
                last = min(end, next_month(month) - timedelta(days=1))
                if contract.valid_to is not None:
                    last = min(last, contract.valid_to)
                if first <= last:
                    by_location[contract.location_id] += await self._contract_charge(
                        contract, first, last
                    )
        return sum(by_location.values(), ZERO)

    async def _contract_charge(self, contract: RentContract, first: date, last: date) -> Decimal:
        """Charge for days `first`..`last`, which must lie within one calendar month."""
        terms = RentTerms(
            rent_type=contract.rent_type,
            fixed_amount=contract.fixed_amount,
            revenue_percent=contract.revenue_percent,
        )
        if contract.rent_type is RentType.FIXED:
            days_in_month = calendar.monthrange(first.year, first.month)[1]
            covered = Decimal((last - first).days + 1) / days_in_month
            return to_money(terms.charge_for(ZERO) * covered)

        machine_ids = [m.id for m in await self.machines.by_location(contract.location_id)]
        totals = await self.revenue.totals_by_channel(first, last + timedelta(days=1), machine_ids)
        return terms.charge_for(sum(totals.values(), ZERO))

    async def _machine_rent_share(self, machine: Machine, start: date, end: date) -> Decimal:
        if machine.location_id is None:
            return ZERO
        location_rent = await self._rent_between(start, end, [machine.location_id])
        neighbours = await self.machines.by_location(machine.location_id)
        return to_money(location_rent / max(len(neighbours), 1))
