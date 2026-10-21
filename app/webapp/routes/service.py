import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from app import __version__
from app.api.deps import ClockDep, SessionDep
from app.db.models import Encashment, Machine, Task
from app.domain.enums import TaskKind, UserRole
from app.domain.inspection import CHECKLIST
from app.repositories import MachineRepository
from app.services.cash import CashError, EncashmentService
from app.services.downtime import DowntimeService
from app.services.notifications import Messages
from app.services.payment_watch import PaymentWatch
from app.services.tasks import TaskError
from app.webapp.auth import CurrentUser
from app.webapp.deps import NotifierDep, TasksDep, UsersDep
from app.webapp.routes.machines import MachineRevenue, machine_revenue
from app.webapp.templating import render, with_toast

router = APIRouter(prefix="/app/service")


@dataclass(frozen=True, slots=True)
class MachineCard:
    machine: Machine
    last_report: date | None
    next_due: date | None
    revenue: MachineRevenue


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
    open_tasks = await tasks.team_open()
    next_due = {t.machine_id: t.due_on for t in open_tasks if t.kind is TaskKind.INSPECTION}

    cards = []
    for machine in await MachineRepository(session).list_active():
        last = await tasks.last_inspection(machine.id)
        last_day = None
        if last is not None and last.completed_at is not None:
            last_day = last.completed_at.astimezone(clock.tz).date()
        revenue = await machine_revenue(session, machine, clock.today())
        cards.append(MachineCard(machine, last_day, next_due.get(machine.id), revenue))

    # Weekly checks live on the machine cards; the list holds one-off and cash tasks.
    listed = [t for t in open_tasks if t.kind is not TaskKind.INSPECTION]
    done = await tasks.team_recently_done(TaskKind.CUSTOM, limit=5)
    # The car video greets the crew on their first visit of the day only.
    show_splash = not user.is_admin and user.splash_seen_on != clock.today()
    if show_splash:
        user.splash_seen_on = clock.today()
        await session.commit()
    return render(
        request,
        "service/home.html",
        downtimes=await DowntimeService(session, clock).all_down(),
        payment_alerts=await PaymentWatch(session, clock).open_alerts(),
        user=user,
        tasks=listed,
        machines=cards,
        done=done,
        back="/app/admin" if user.is_admin else None,
        show_splash=show_splash,
        version=__version__,
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_page(
    request: Request, task_id: int, user: CurrentUser, tasks: TasksDep, session: SessionDep
) -> HTMLResponse:
    task = await _task_or_404(tasks, task_id)
    if task.encashment_id is not None:
        encashment = await EncashmentService(session, request.app.state.clock).get(
            task.encashment_id
        )
        return render(request, "service/cash_task.html", task=task, encashment=encashment)
    return render(request, "service/task.html", task=task)


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
    request: Request,
    machine_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    session: SessionDep,
    back: Literal["home", "machine"] = "home",
) -> HTMLResponse:
    machine = await _machine_or_404(session, machine_id)
    return render(
        request,
        "service/report.html",
        machine=machine,
        last=await tasks.last_inspection(machine.id),
        checklist=CHECKLIST,
        back_url=f"/app/machines/{machine.id}" if back == "machine" else "/app/service",
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
    took = {key: form.get(key) for key in ("took_bills", "took_coins")}
    if None in took.values():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Отметьте, забирали ли деньги")
    try:
        outcome = await tasks.submit_report(
            machine, user, results, comment=str(form.get("comment") or "")
        )
    except TaskError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    encashment = await EncashmentService(session, clock).collect(
        machine,
        user,
        outcome.task,
        bills=took["took_bills"] == "yes",
        coins=took["took_coins"] == "yes",
    )
    await session.commit()

    background.add_task(
        notifier.send,
        await users.telegram_ids(UserRole.ADMIN),
        Messages.inspection_report(outcome, user.name, encashment),
    )
    page = await home(request, user, tasks, session, clock)
    return with_toast(page, "Спасибо! Отчёт отправлен")


@router.post("/reports/{report_id}/delete")
async def delete_report(
    report_id: int, user: CurrentUser, tasks: TasksDep, session: SessionDep
) -> Response:
    report = await _task_or_404(tasks, report_id)
    machine_id = report.machine_id
    try:
        await tasks.delete_report(report)
    except TaskError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    target = f"/app/machines/{machine_id}" if machine_id else "/app/service"
    return Response(
        headers={
            "HX-Location": json.dumps({"path": target, "target": "#view"}),
            "HX-Trigger": json.dumps({"toast": "Отчёт удалён"}),
        }
    )


def _amount(raw: object) -> Decimal | None:
    text = str(raw or "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Сумма указана неверно") from exc


async def _encashment_or_404(
    session: SessionDep, clock: ClockDep, encashment_id: int
) -> Encashment:
    encashment = await EncashmentService(session, clock).get(encashment_id)
    if encashment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Инкассация не найдена")
    return encashment


@router.post("/cash/{encashment_id}/count", response_class=HTMLResponse)
async def count_cash(
    request: Request,
    encashment_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    users: UsersDep,
    session: SessionDep,
    clock: ClockDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
) -> HTMLResponse:
    encashment = await _encashment_or_404(session, clock, encashment_id)
    form = await request.form()
    try:
        await EncashmentService(session, clock).count(
            encashment, user, bills=_amount(form.get("bills")), coins=_amount(form.get("coins"))
        )
    except CashError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    background.add_task(
        notifier.send,
        await users.telegram_ids(UserRole.ADMIN),
        Messages.cash_counted(encashment, user.name),
    )
    page = await home(request, user, tasks, session, clock)
    return with_toast(page, "Записал! Теперь деньги нужно отнести в банк")


@router.post("/cash/{encashment_id}/deposit", response_class=HTMLResponse)
async def deposit_cash(
    request: Request,
    encashment_id: int,
    user: CurrentUser,
    tasks: TasksDep,
    users: UsersDep,
    session: SessionDep,
    clock: ClockDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
    amount: Annotated[str, Form()],
    deposited_on: Annotated[date, Form()],
) -> HTMLResponse:
    encashment = await _encashment_or_404(session, clock, encashment_id)
    value = _amount(amount)
    if value is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Впишите сумму")
    try:
        await EncashmentService(session, clock).deposit(
            encashment, user, amount=value, on=deposited_on
        )
    except CashError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    background.add_task(
        notifier.send,
        await users.telegram_ids(UserRole.ADMIN),
        Messages.cash_deposited(encashment, user.name),
    )
    page = await home(request, user, tasks, session, clock)
    return with_toast(page, "Готово, деньги на счёте")
