from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import ClockDep, SessionDep
from app.db.models import CashHistoryEntry, Expense, Machine
from app.domain.enums import ExpenseCategory, PaidFrom
from app.domain.finance import COST_OF_SALES
from app.domain.periods import month_start, previous_month
from app.formatting import MONTHS_SHORT
from app.repositories import ExpenseRepository, MachineRepository
from app.services.cash_history import CashHistoryError, CashHistoryInput, CashHistoryService
from app.services.finance import FinanceService, MachineNotFoundError
from app.webapp.auth import AdminUser
from app.webapp.charts import BarChart, Series
from app.webapp.routes.admin.common import admin_page, optional_int

router = APIRouter(prefix="/app/admin")

CHART_MONTHS = 12


def parse_money(raw: str, field: str = "Сумма") -> Decimal:
    try:
        value = Decimal(raw.replace("\xa0", "").replace(" ", "").replace(",", ".") or "0")
    except InvalidOperation as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} указана неверно"
        ) from exc
    if value < 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} не может быть меньше нуля"
        )
    return value


@router.get("/ofr", response_class=HTMLResponse)
async def income_statement(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    start: date | None = None,
    end: date | None = None,
    machine: int | None = None,
    all_time: bool = False,
    toast: str | None = None,
) -> HTMLResponse:
    today = clock.today()
    finance = FinanceService(session)

    if all_time:
        start, end = await finance.first_day(machine) or today, today
    start = start or month_start(today)
    end = min(end or today, today)
    if start > end:
        start, end = end, start

    chart_from = month_start(today)
    for _month in range(CHART_MONTHS - 1):
        chart_from = previous_month(chart_from)
    try:
        statement = await finance.statement(start, end, machine)
        months = await finance.pnl_range(chart_from, today, machine)
    except MachineNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден") from exc

    chart = BarChart(
        [MONTHS_SHORT[m.period.month - 1] for m in months],
        [
            Series("выручка", [m.total_revenue for m in months], "bar-revenue"),
            Series("прибыль", [m.net_profit for m in months], "bar-profit"),
        ],
    ).render()

    expenses = (
        await session.scalars(
            select(Expense)
            .options(selectinload(Expense.machine))
            .order_by(Expense.spent_on.desc(), Expense.id.desc())
            .limit(30)
        )
    ).all()
    last_month = previous_month(month_start(today))
    return await admin_page(
        request,
        session,
        "admin/statement.html",
        tab="ofr",
        statement=statement,
        cost_lines=COST_OF_SALES,
        chart=chart,
        expenses=expenses,
        cash_history=await CashHistoryService(session, clock).entries(),
        machines=await MachineRepository(session).list_active(),
        selected=machine,
        all_time=all_time,
        presets=[
            ("За день", today, today),
            ("За неделю", today - timedelta(days=6), today),
            ("Этот месяц", month_start(today), today),
            ("Прошлый месяц", last_month, month_start(today) - timedelta(days=1)),
        ],
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
    paid_from: Annotated[PaidFrom, Form()] = PaidFrom.PERSONAL,
    machine_id: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
) -> HTMLResponse:
    value = parse_money(amount)
    if value == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Сумма должна быть больше нуля")
    machine = optional_int(machine_id)
    if machine is not None and await session.get(Machine, machine) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")

    await ExpenseRepository(session).add(
        Expense(
            amount=value,
            spent_on=spent_on,
            category=category,
            paid_from=paid_from,
            machine_id=machine,
            description=description.strip() or None,
            created_by=admin.telegram_id,
        )
    )
    return await income_statement(request, admin, session, clock, toast="Расход добавлен")


@router.delete("/expenses/{expense_id}", response_class=HTMLResponse)
async def delete_expense(
    request: Request, expense_id: int, admin: AdminUser, session: SessionDep, clock: ClockDep
) -> HTMLResponse:
    repo = ExpenseRepository(session)
    expense = await repo.get(expense_id)
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Расход не найден")
    await repo.delete(expense)
    return await income_statement(request, admin, session, clock, toast="Расход удалён")


@router.post("/cash-history", response_class=HTMLResponse)
async def add_cash_history(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    machine_id: Annotated[int, Form()],
    first_day: Annotated[date, Form()],
    last_day: Annotated[date, Form()],
    coins: Annotated[str, Form()] = "",
    bills: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
) -> HTMLResponse:
    data = CashHistoryInput(
        machine_id=machine_id,
        first_day=first_day,
        last_day=last_day,
        coins=parse_money(coins, "Сумма монет"),
        bills=parse_money(bills, "Сумма купюр"),
        note=note,
    )
    try:
        await CashHistoryService(session, clock).add(data)
    except CashHistoryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await income_statement(
        request, admin, session, clock, all_time=True, toast="Наличные за прошлый период внесены"
    )


@router.delete("/cash-history/{entry_id}", response_class=HTMLResponse)
async def delete_cash_history(
    request: Request, entry_id: int, admin: AdminUser, session: SessionDep, clock: ClockDep
) -> HTMLResponse:
    entry = await session.get(CashHistoryEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    await CashHistoryService(session, clock).remove(entry)
    return await income_statement(
        request, admin, session, clock, all_time=True, toast="Запись удалена"
    )
