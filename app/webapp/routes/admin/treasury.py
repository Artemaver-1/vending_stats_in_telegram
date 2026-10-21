from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.db.models import Payout
from app.domain.enums import UserRole
from app.services.cash import EncashmentService
from app.services.treasury import TreasuryService
from app.webapp.auth import AdminUser
from app.webapp.deps import UsersDep
from app.webapp.routes.admin.common import admin_page
from app.webapp.routes.admin.statement import parse_money

router = APIRouter(prefix="/app/admin/finance")


@router.get("", response_class=HTMLResponse)
async def finance_page(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    users: UsersDep,
    toast: str | None = None,
) -> HTMLResponse:
    treasury = TreasuryService(session, clock)
    team = [u.name for role in (UserRole.ADMIN, UserRole.WORKER) for u in await users.active(role)]
    return await admin_page(
        request,
        session,
        "admin/finance.html",
        tab="finance",
        balances=await treasury.balances(),
        encashments=await EncashmentService(session, clock).recent(limit=20),
        payouts=await treasury.payouts(),
        paid_by=await treasury.paid_by_recipient(),
        flows=await treasury.months(),
        team=team,
        toast=toast,
    )


@router.post("/ledger", response_class=HTMLResponse)
async def open_ledger(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    users: UsersDep,
    opened_on: Annotated[date, Form()],
    bank_opening: Annotated[str, Form()] = "",
) -> HTMLResponse:
    await TreasuryService(session, clock).open_ledger(
        opened_on, parse_money(bank_opening, "Остаток")
    )
    return await finance_page(request, admin, session, clock, users, toast="Начало учёта сохранено")


@router.post("/payouts", response_class=HTMLResponse)
async def add_payout(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    users: UsersDep,
    paid_on: Annotated[date, Form()],
    amount: Annotated[str, Form()],
    recipient: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await TreasuryService(session, clock).add_payout(
            paid_on, parse_money(amount), recipient, note
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await finance_page(request, admin, session, clock, users, toast="Выплата записана")


@router.delete("/payouts/{payout_id}", response_class=HTMLResponse)
async def delete_payout(
    request: Request,
    payout_id: int,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    users: UsersDep,
) -> HTMLResponse:
    payout = await session.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Выплата не найдена")
    await session.delete(payout)
    await session.flush()
    return await finance_page(request, admin, session, clock, users, toast="Выплата удалена")
