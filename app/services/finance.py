from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Machine, RentContract
from app.domain.enums import RentType
from app.domain.finance import (
    ZERO,
    MonthlyPnL,
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


class MachineNotFoundError(LookupError):
    pass


class FinanceService:
    """Builds profit-and-loss reports.

    Rent is calculated from contract terms rather than taken from recorded payments,
    so a month's profit is correct even before the rent for it has been paid.
    In a single-machine report the location rent is split evenly between the
    machines standing there, and shared expenses (not tied to a machine) are left out.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.revenue = RevenueRepository(session)
        self.expenses = ExpenseRepository(session)
        self.contracts = RentContractRepository(session)
        self.machines = MachineRepository(session)

    async def monthly_pnl(self, period: date, machine_id: int | None = None) -> MonthlyPnL:
        start = month_start(period)
        end = next_month(start)

        if machine_id is None:
            return MonthlyPnL(
                period=start,
                revenue=await self.revenue.totals_by_channel(start, end),
                expenses=await self.expenses.totals_by_category(start, end),
                rent=await self._rent_for_month(start, end),
            )

        machine = await self._get_machine(machine_id)
        return MonthlyPnL(
            period=start,
            revenue=await self.revenue.totals_by_channel(start, end, [machine.id]),
            expenses=await self.expenses.totals_by_category(
                start, end, [machine.id], include_shared=False
            ),
            rent=await self._machine_rent_share(machine, start, end),
        )

    async def pnl_range(
        self, first: date, last: date, machine_id: int | None = None
    ) -> list[MonthlyPnL]:
        return [await self.monthly_pnl(period, machine_id) for period in iter_months(first, last)]

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

    async def _get_machine(self, machine_id: int) -> Machine:
        machine = await self.machines.get(machine_id)
        if machine is None:
            raise MachineNotFoundError(machine_id)
        return machine

    async def _rent_for_month(
        self, start: date, end: date, location_ids: list[int] | None = None
    ) -> Decimal:
        contracts = await self.contracts.active_between(start, end, location_ids)
        rent_by_location: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for contract in contracts:
            rent_by_location[contract.location_id] += await self.rent_charge(contract, start)
        return sum(rent_by_location.values(), ZERO)

    async def rent_charge(self, contract: RentContract, period: date) -> Decimal:
        """What the contract costs for the month containing `period`."""
        start = month_start(period)
        end = next_month(start)
        terms = RentTerms(
            rent_type=contract.rent_type,
            fixed_amount=contract.fixed_amount,
            revenue_percent=contract.revenue_percent,
        )
        location_revenue = ZERO
        if contract.rent_type is RentType.PERCENT:
            machine_ids = [m.id for m in await self.machines.by_location(contract.location_id)]
            totals = await self.revenue.totals_by_channel(start, end, machine_ids)
            location_revenue = sum(totals.values(), ZERO)
        return terms.charge_for(location_revenue)

    async def _machine_rent_share(self, machine: Machine, start: date, end: date) -> Decimal:
        if machine.location_id is None:
            return ZERO
        location_rent = await self._rent_for_month(start, end, [machine.location_id])
        neighbours = await self.machines.by_location(machine.location_id)
        return to_money(location_rent / max(len(neighbours), 1))
