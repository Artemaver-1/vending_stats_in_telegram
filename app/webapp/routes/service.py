from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.db.models import Machine, Task
from app.domain.enums import TaskKind, UserRole
from app.domain.inspection import CHECKLIST
from app.repositories import MachineRepository
from app.services.notifications import Messages
from app.services.tasks import TaskError
from app.webapp.auth import CurrentUser
from app.webapp.deps import NotifierDep, TasksDep, UsersDep
from app.webapp.templating import render, with_toast

router = APIRouter(prefix="/app/service")


@dataclass(frozen=True, slots=True)
class MachineCard:
    machine: Machine
    last_report: date | None
    next_due: date | None


async def _task_or_404(tasks: TasksDep, task_id: int) -> Task:
    task = await tasks.get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    return task


async def _machine_or_404(session: SessionDep, machine_id: int) -> Machine:
    machine = await session.get(Machine, machine_id)
    if machine is None or not machine.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")
    return machine


@router.get("", response_class=HTMLResponse)
async def home(
    request: Request, user: CurrentUser, tasks: TasksDep, session: SessionDep, clock: ClockDep
) -> HTMLResponse:
    open_tasks = await tasks.open_for(user)
    next_due = {t.machine_id: t.due_on for t in open_tasks if t.kind is TaskKind.INSPECTION}

    cards = []
    for machine in await MachineRepository(session).list_active():
        last = await tasks.last_inspection(machine.id)
        last_day = None
        if last is not None and last.completed_at is not None:
            last_day = last.completed_at.astimezone(clock.tz).date()
        cards.append(MachineCard(machine, last_day, next_due.get(machine.id)))

    # Weekly checks live on the machine cards, so the task list holds only one-off tasks.
    listed = [t for t in open_tasks if t.kind is TaskKind.CUSTOM]
    done = [t for t in await tasks.done_by(user, limit=5) if t.kind is TaskKind.CUSTOM]
    return render(
        request,
        "service/home.html",
        user=user,
        tasks=listed,
        machines=cards,
        done=done,
        back="/app/admin" if user.is_admin else None,
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_page(
    request: Request, task_id: int, user: CurrentUser, tasks: TasksDep
) -> HTMLResponse:
    return render(request, "service/task.html", task=await _task_or_404(tasks, task_id))


@router.post("/tasks/{task_id}/done", response_class=HTMLResponse)
async def complete_task(
    request: Request,
    task_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    users: UsersDep,
    session: SessionDep,
    clock: ClockDep,
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
    page = await home(request, user, tasks, session, clock)
    return with_toast(page, "Отлично, задача закрыта")


@router.get("/machines/{machine_id}/report", response_class=HTMLResponse)
async def report_form(
    request: Request, machine_id: int, user: CurrentUser, tasks: TasksDep, session: SessionDep
) -> HTMLResponse:
    machine = await _machine_or_404(session, machine_id)
    return render(
        request,
        "service/report.html",
        machine=machine,
        last=await tasks.last_inspection(machine.id),
        checklist=CHECKLIST,
    )


@router.post("/machines/{machine_id}/report", response_class=HTMLResponse)
async def submit_report(
    request: Request,
    machine_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    users: UsersDep,
    session: SessionDep,
    clock: ClockDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
) -> HTMLResponse:
    machine = await _machine_or_404(session, machine_id)
    form = await request.form()
    results = {item.key: form.get(item.key) == "yes" for item in CHECKLIST if form.get(item.key)}
    try:
        outcome = await tasks.submit_report(
            machine, user, results, comment=str(form.get("comment") or "")
        )
    except TaskError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()

    background.add_task(
        notifier.send,
        await users.telegram_ids(UserRole.ADMIN),
        Messages.inspection_report(outcome, user.name),
    )
    page = await home(request, user, tasks, session, clock)
    return with_toast(page, "Спасибо! Отчёт отправлен")
