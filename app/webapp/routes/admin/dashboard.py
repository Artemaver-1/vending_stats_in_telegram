from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.db.models import Machine
from app.domain.enums import TaskStatus
from app.formatting import MONTHS_GENITIVE
from app.repositories import MachineRepository
from app.services.finance import FinanceService
from app.webapp.auth import AdminUser
from app.webapp.deps import RentDep, TasksDep, UsersDep
from app.webapp.routes.admin.common import admin_page

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
    )
