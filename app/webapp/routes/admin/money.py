from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import ClockDep, SessionDep
from app.db.models import Expense, Machine
from app.domain.enums import ExpenseCategory
from app.domain.finance import ZERO, IncomeStatement
from app.domain.periods import month_start, next_month, previous_month
from app.formatting import MONTHS_SHORT
from app.repositories import ExpenseRepository, MachineRepository
from app.services.finance import FinanceService
from app.webapp.auth import AdminUser
from app.webapp.charts import BarChart, Series
from app.webapp.routes.admin.common import admin_page, optional_int

router = APIRouter(prefix="/app/admin")

CHART_MONTHS = 12


@dataclass(frozen=True, slots=True)
class Totals:
    revenue: Decimal
    expenses: Decimal
    profit: Decimal
    investment: Decimal


def _parse_month(value: str | None, today: date) -> date:
    current = month_start(today)
    if not value:
        return current
    try:
        year, month = map(int, value.split("-"))
        return min(date(year, month, 1), current)
    except ValueError:
        return current


@router.get("/economics", response_class=HTMLResponse)
async def economics(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    month: str | None = None,
    toast: str | None = None,
) -> HTMLResponse:
    today = clock.today()
    period = _parse_month(month, today)
    finance = FinanceService(session)
    machines = await MachineRepository(session).list()

    launches = [m.launched_on for m in machines if m.launched_on]
    history: list[IncomeStatement] = []
    if launches:
        history = await finance.pnl_range(min(launches), today)
    by_period = {p.period: p for p in history}
    pnl = by_period.get(period) or await finance.monthly_pnl(period)

    recent = history[-CHART_MONTHS:]
    chart = BarChart(
        [MONTHS_SHORT[p.period.month - 1] for p in recent],
        [
            Series("выручка", [p.total_revenue for p in recent], "bar-revenue"),
            Series("прибыль", [p.net_profit for p in recent], "bar-profit"),
        ],
    ).render()

    paybacks = [("Весь бизнес", await finance.business_payback(today))]
    for machine in machines:
        if machine.is_active:
            paybacks.append((machine.name, await finance.machine_payback(machine.id, today)))

    expenses = (
        await session.scalars(
            select(Expense)
            .options(selectinload(Expense.machine))
            .order_by(Expense.spent_on.desc(), Expense.id.desc())
            .limit(20)
        )
    ).all()

    return await admin_page(
        request,
        session,
        "admin/economics.html",
        tab="money",
        pnl=pnl,
        prev_month=previous_month(period),
        next_month=next_month(period) if period < month_start(today) else None,
        chart=chart,
        paybacks=paybacks,
        totals=Totals(
            revenue=sum((p.total_revenue for p in history), ZERO),
            expenses=sum((p.total_expenses for p in history), ZERO),
            profit=sum((p.net_profit for p in history), ZERO),
            investment=sum((m.purchase_cost for m in machines), ZERO),
        ),
        expenses=expenses,
        machines=[m for m in machines if m.is_active],
        toast=toast,
    )


@router.post("/expenses", response_class=HTMLResponse)
async def add_expense(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    amount: Annotated[str, Form()],
    spent_on: Annotated[date, Form()],
    category: Annotated[ExpenseCategory, Form()],
    machine_id: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        value = Decimal(amount.replace(",", ".").replace(" ", ""))
    except InvalidOperation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Сумма указана неверно") from exc
    if value <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Сумма должна быть больше нуля")
    machine = optional_int(machine_id)
    if machine is not None and await session.get(Machine, machine) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")

    await ExpenseRepository(session).add(
        Expense(
            amount=value,
            spent_on=spent_on,
            category=category,
            machine_id=machine,
            description=description.strip() or None,
            created_by=admin.telegram_id,
        )
    )
    return await economics(
        request, admin, session, clock, spent_on.strftime("%Y-%m"), toast="Расход добавлен"
    )


@router.delete("/expenses/{expense_id}", response_class=HTMLResponse)
async def delete_expense(
    request: Request, expense_id: int, admin: AdminUser, session: SessionDep, clock: ClockDep
) -> HTMLResponse:
    repo = ExpenseRepository(session)
    expense = await repo.get(expense_id)
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Расход не найден")
    month = expense.spent_on.strftime("%Y-%m")
    await repo.delete(expense)
    return await economics(request, admin, session, clock, month, toast="Расход удалён")
