from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Machine, Task
from app.domain.enums import TaskKind, UserRole
from app.domain.inspection import CHECKLIST
from app.services.notifications import Messages
from app.services.tasks import TaskError
from app.webapp.auth import CurrentUser
from app.webapp.deps import NotifierDep, TasksDep, UsersDep
from app.webapp.templating import render, with_toast

router = APIRouter(prefix="/app/service")


async def _task_or_404(tasks: TasksDep, task_id: int) -> Task:
    task = await tasks.get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    return task


@router.get("", response_class=HTMLResponse)
async def home(
    request: Request, user: CurrentUser, tasks: TasksDep, session: SessionDep
) -> HTMLResponse:
    broken = (
        await session.scalars(
            select(Machine).where(Machine.is_active, Machine.broken_since.is_not(None))
        )
    ).all()
    return render(
        request,
        "service/home.html",
        user=user,
        tasks=await tasks.open_for(user),
        done=await tasks.done_by(user, limit=5),
        broken=broken,
        back="/app/admin" if user.is_admin else None,
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_page(
    request: Request, task_id: int, user: CurrentUser, tasks: TasksDep
) -> HTMLResponse:
    task = await _task_or_404(tasks, task_id)
    if task.kind is TaskKind.INSPECTION and task.is_open:
        return render(request, "service/inspection.html", task=task, checklist=CHECKLIST)
    return render(request, "service/task.html", task=task)


@router.post("/tasks/{task_id}/done", response_class=HTMLResponse)
async def complete_task(
    request: Request,
    task_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    users: UsersDep,
    session: SessionDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
    comment: Annotated[str, Form()] = "",
) -> HTMLResponse:
    task = await _task_or_404(tasks, task_id)
    try:
        await tasks.complete(task, user, comment)
    except TaskError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    task = await _task_or_404(tasks, task_id)

    if not user.is_admin:
        background.add_task(
            notifier.send, await users.telegram_ids(UserRole.ADMIN), Messages.task_done(task)
        )
    return with_toast(await home(request, user, tasks, session), "Отлично, задача закрыта")


@router.post("/tasks/{task_id}/inspection", response_class=HTMLResponse)
async def submit_inspection(
    request: Request,
    task_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    users: UsersDep,
    session: SessionDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
) -> HTMLResponse:
    task = await _task_or_404(tasks, task_id)
    form = await request.form()
    results = {item.key: form.get(item.key) == "yes" for item in CHECKLIST if form.get(item.key)}
    try:
        outcome = await tasks.submit_inspection(
            task,
            user,
            results,
            order=str(form.get("order") or ""),
            comment=str(form.get("comment") or ""),
        )
    except TaskError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()

    background.add_task(
        notifier.send,
        await users.telegram_ids(UserRole.ADMIN),
        Messages.inspection_report(outcome, user.name),
    )
    toast = "Спасибо! Отчёт отправлен" if outcome.needs_attention else "Спасибо, всё записано"
    return with_toast(await home(request, user, tasks, session), toast)


@router.post("/machines/{machine_id}/repair-check", response_class=HTMLResponse)
async def repair_check(
    request: Request, machine_id: int, user: CurrentUser, tasks: TasksDep, session: SessionDep
) -> HTMLResponse:
    machine = await session.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")
    task = await tasks.start_repair_check(machine)
    await session.commit()
    task = await _task_or_404(tasks, task.id)
    return render(request, "service/inspection.html", task=task, checklist=CHECKLIST)
