from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.repositories import MachineRepository
from app.services.reconciliation import CardReconciliationService
from app.webapp.auth import AdminUser
from app.webapp.routes.admin.common import admin_page

router = APIRouter(prefix="/app/admin")


@router.get("/reconciliation", response_class=HTMLResponse)
async def card_reconciliation(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    machine: int | None = None,
) -> HTMLResponse:
    machines = await MachineRepository(session).list_active()
    if not machines:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомеров нет")
    selected = next((m for m in machines if m.id == machine), machines[0])
    report = await CardReconciliationService(session, clock).for_machine(selected)
    return await admin_page(
        request,
        session,
        "admin/reconciliation.html",
        tab="home",
        back="/app/admin/machines",
        machines=machines,
        selected=selected,
        report=report,
    )
