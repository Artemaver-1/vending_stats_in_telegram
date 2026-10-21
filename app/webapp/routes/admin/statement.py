from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.domain.finance import COST_OF_SALES
from app.domain.periods import month_start, previous_month
from app.repositories import MachineRepository
from app.services.finance import FinanceService, MachineNotFoundError
from app.webapp.auth import AdminUser
from app.webapp.routes.admin.common import admin_page

router = APIRouter(prefix="/app/admin")


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
) -> HTMLResponse:
    today = clock.today()
    finance = FinanceService(session)

    if all_time:
        start, end = await finance.first_day(machine) or today, today
    start = start or month_start(today)
    end = min(end or today, today)
    if start > end:
        start, end = end, start

    try:
        statement = await finance.statement(start, end, machine)
    except MachineNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден") from exc

    last_month = previous_month(month_start(today))
    presets = {
        "this_month": (month_start(today), today),
        "last_month": (last_month, month_start(today) - timedelta(days=1)),
    }
    return await admin_page(
        request,
        session,
        "admin/statement.html",
        tab="ofr",
        statement=statement,
        cost_lines=COST_OF_SALES,
        machines=await MachineRepository(session).list_active(),
        selected=machine,
        all_time=all_time,
        presets=presets,
    )
