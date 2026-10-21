from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import ClockDep, SessionDep
from app.db.models import Machine, SyncState
from app.domain.enums import TaskStatus
from app.formatting import MONTHS_GENITIVE
from app.repositories import MachineRepository
from app.services.finance import FinanceService
from app.webapp.auth import AdminUser
from app.webapp.deps import RentDep, TasksDep, UsersDep
from app.webapp.routes.admin.common import admin_page
from app.webapp.templating import with_toast
from app.worker.jobs import TelemetryJobs

router = APIRouter()


@dataclass(frozen=True, slots=True)
class MachineSummary:
    machine: Machine
    revenue: Decimal
    last_check: date | None


@router.get("/app/admin", response_class=HTMLResponse)
async def home(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
    rent: RentDep,
    users: UsersDep,
    toast: str | None = None,
) -> HTMLResponse:
    today = clock.today()
    finance = FinanceService(session)

    machines = []
    for machine in await MachineRepository(session).list_active():
        pnl = await finance.monthly_pnl(today, machine.id)
        last = await tasks.last_inspection(machine.id)
        last_check = (
            last.completed_at.astimezone(clock.tz).date() if last and last.completed_at else None
        )
        machines.append(MachineSummary(machine, pnl.total_revenue, last_check))

    await rent.sync_accruals()
    rent_due = [p for p in await rent.payments() if not p.is_paid and (p.due_on - today).days <= 5]
    overdue = [t for t in await tasks.with_status(TaskStatus.OPEN) if t.due_on < today]
    pending_users = sum(1 for u in await users.list_all() if not u.is_active)
    checked = [s.machine.status_checked_at for s in machines if s.machine.status_checked_at]
    failing = await session.scalars(select(SyncState).where(SyncState.last_error.is_not(None)))
    sync_errors = {state.last_error for state in failing}

    return await admin_page(
        request,
        session,
        "admin/home.html",
        tab="home",
        pnl=await finance.monthly_pnl(today),
        payback=await finance.business_payback(today),
        machines=machines,
        overdue=overdue,
        rent_due=rent_due,
        pending_users=pending_users,
        month_name=MONTHS_GENITIVE[today.month - 1],
        synced_at=max(checked) if checked else None,
        sync_errors=sorted(e for e in sync_errors if e),
        toast=toast,
    )


@router.post("/app/admin/sync", response_class=HTMLResponse)
async def refresh_smartvend(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
    rent: RentDep,
    users: UsersDep,
) -> HTMLResponse:
    telemetry: TelemetryJobs | None = getattr(request.app.state, "telemetry", None)
    if telemetry is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SmartVend не настроен")
    failure = await telemetry.refresh_all()
    # The sync committed in its own sessions; drop anything this one cached before it.
    session.expire_all()
    page = await home(request, admin, session, clock, tasks, rent, users)
    # A 5xx would be swapped for Cloudflare's own error page on the way through the tunnel,
    # so a failed refresh is a normal screen with an error toast.
    if failure:
        return with_toast(page, failure, error=True)
    return with_toast(page, "Данные SmartVend обновлены")
