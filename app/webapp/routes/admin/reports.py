from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import SessionDep
from app.repositories import MachineRepository
from app.services.tasks import TaskError
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
    toast: str | None = None,
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
        toast=toast,
    )


@router.post("/reports/{report_id}/comment", response_class=HTMLResponse)
async def edit_report_comment(
    request: Request,
    report_id: int,
    admin: AdminUser,
    session: SessionDep,
    tasks: TasksDep,
    comment: Annotated[str, Form()] = "",
    machine: int | None = None,
) -> HTMLResponse:
    report = await tasks.get(report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Отчёт не найден")
    try:
        await tasks.set_report_comment(report, comment)
    except TaskError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await reports_page(request, admin, session, tasks, machine, toast="Комментарий сохранён")


@router.post("/reports/{report_id}/delete", response_class=HTMLResponse)
async def delete_report(
    request: Request,
    report_id: int,
    admin: AdminUser,
    session: SessionDep,
    tasks: TasksDep,
    machine: int | None = None,
) -> HTMLResponse:
    report = await tasks.get(report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Отчёт не найден")
    try:
        await tasks.delete_report(report)
    except TaskError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await reports_page(request, admin, session, tasks, machine, toast="Отчёт удалён")
