from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import ClockDep, SessionDep
from app.domain.enums import ExpenseCategory, PaymentChannel
from app.domain.finance import IncomeStatement, PaybackStatus
from app.services.finance import FinanceService, MachineNotFoundError

router = APIRouter(prefix="/finance", tags=["finance"])


class PnlOut(BaseModel):
    period: date
    revenue: dict[PaymentChannel, Decimal]
    expenses: dict[ExpenseCategory, Decimal]
    rent: Decimal
    total_revenue: Decimal
    total_expenses: Decimal
    net_profit: Decimal

    @classmethod
    def from_domain(cls, pnl: IncomeStatement) -> "PnlOut":
        return cls(
            period=pnl.period,
            revenue=pnl.revenue,
            expenses=pnl.expenses,
            rent=pnl.rent,
            total_revenue=pnl.total_revenue,
            total_expenses=pnl.total_expenses,
            net_profit=pnl.net_profit,
        )


class PaybackOut(BaseModel):
    investment: Decimal
    earned: Decimal
    remaining: Decimal
    progress: float
    reached_in: date | None

    @classmethod
    def from_domain(cls, status_: PaybackStatus) -> "PaybackOut":
        return cls(
            investment=status_.investment,
            earned=status_.earned,
            remaining=status_.remaining,
            progress=status_.progress,
            reached_in=status_.reached_in,
        )


@router.get("/monthly")
async def monthly(
    session: SessionDep,
    first: Annotated[date, Query(description="Any day of the first month")],
    last: Annotated[date, Query(description="Any day of the last month")],
    machine_id: int | None = None,
) -> list[PnlOut]:
    if first > last:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "first must not be after last")
    try:
        months = await (await FinanceService.snapshot(session)).pnl_range(first, last, machine_id)
    except MachineNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found") from exc
    return [PnlOut.from_domain(m) for m in months]


@router.get("/payback")
async def payback(
    session: SessionDep, clock: ClockDep, machine_id: int | None = None
) -> PaybackOut:
    service = await FinanceService.snapshot(session)
    try:
        if machine_id is None:
            result = await service.business_payback(clock.today())
        else:
            result = await service.machine_payback(machine_id, clock.today())
    except MachineNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found") from exc
    return PaybackOut.from_domain(result)
