from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.deps import SessionDep
from app.repositories import MachineRepository
from app.webapp.auth import AdminUser
from app.webapp.deps import TasksDep
from app.webapp.routes.admin.common import admin_page

router = APIRouter(prefix="/app/admin")


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    tasks: TasksDep,
    machine: int | None = None,
) -> HTMLResponse:
    reports = await tasks.reports(machine_id=machine)
    # Highlight what arrived since the last visit, then clear the badge.
    unseen = {r.id for r in reports if r.seen_at is None}
    await tasks.mark_reports_seen()
    return await admin_page(
        request,
        session,
        "admin/reports.html",
        tab="reports",
        reports=reports,
        unseen=unseen,
        machines=await MachineRepository(session).list_active(),
        selected=machine,
    )
