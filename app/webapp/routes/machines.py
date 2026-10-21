from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.db.models import Machine
from app.domain.periods import month_start, next_month, previous_month
from app.services.downtime import DowntimeService
from app.services.finance import FinanceService
from app.services.uptime import UptimeService
from app.webapp.auth import CurrentUser
from app.webapp.deps import TasksDep
from app.webapp.templating import render

router = APIRouter(prefix="/app/machines")

RECENT_DAYS = 30
WEEKS_DAYS = 28


@dataclass(frozen=True, slots=True)
class MachineRevenue:
    last_30_days: Decimal
    this_month: Decimal


async def machine_revenue(session: SessionDep, machine: Machine, today: date) -> MachineRevenue:
    """Takings only: the service team sees how a machine earns, not the business's profit."""
    finance = FinanceService(session)
    recent = await finance.statement(today - timedelta(days=RECENT_DAYS - 1), today, machine.id)
    month = await finance.statement(month_start(today), today, machine.id)
    return MachineRevenue(recent.total_revenue, month.total_revenue)


@router.get("/{machine_id}", response_class=HTMLResponse)
async def machine_page(
    request: Request,
    machine_id: int,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
    view: Literal["weeks", "year", "month"] = "weeks",
    year: int | None = None,
    month: int | None = None,
) -> HTMLResponse:
    machine = await session.get(Machine, machine_id)
    if machine is None or not machine.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")

    today = clock.today()
    uptime = UptimeService(session, clock)
    first_year = machine.launched_on.year if machine.launched_on else today.year
    years = list(range(first_year, today.year + 1))
    year = min(max(year or today.year, first_year), today.year)

    context: dict[str, Any] = {}
    shares: dict[date, float | None]
    if view == "weeks":
        shares = await uptime.daily(machine, today - timedelta(days=WEEKS_DAYS - 1), today)
        context["days"] = shares
    elif view == "year":
        shares = await uptime.monthly(machine, year)
        context["months"] = shares
    else:
        shown = min(date(year, month, 1) if month else month_start(today), month_start(today))
        last = min(next_month(shown) - timedelta(days=1), today)
        shares = await uptime.daily(machine, shown, last)
        context.update(
            days=shares,
            shown=shown,
            prev_month=previous_month(shown),
            next_month=next_month(shown) if shown < month_start(today) else None,
        )
    known = [v for v in shares.values() if v is not None]

    return render(
        request,
        "machines/detail.html",
        user=user,
        machine=machine,
        revenue=await machine_revenue(session, machine, today),
        reports=await tasks.reports(machine.id, limit=5),
        downtime=await DowntimeService(session, clock).for_machine(machine),
        view=view,
        year=year,
        years=years,
        average=sum(known) / len(known) if known else None,
        back="/app/admin" if user.is_admin else "/app/service",
        **context,
    )
