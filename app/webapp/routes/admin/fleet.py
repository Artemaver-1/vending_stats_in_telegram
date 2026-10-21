from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import ClockDep, SessionDep
from app.db.models import Machine, Task, User
from app.formatting import rub
from app.integrations.vendista import VendistaExportError, read_transactions
from app.repositories import MachineRepository
from app.services.uptime import UptimeService
from app.services.vendista import VendistaImporter
from app.webapp.auth import AdminUser
from app.webapp.deps import NotifierDep, TasksDep, UsersDep
from app.webapp.routes.admin.common import admin_page

router = APIRouter(prefix="/app/admin")

UPTIME_DAYS = 28


@dataclass(frozen=True, slots=True)
class MachineCard:
    machine: Machine
    uptime: dict[date, float | None]
    last_check: Task | None

    @property
    def average(self) -> float | None:
        known = [v for v in self.uptime.values() if v is not None]
        return sum(known) / len(known) if known else None


@router.get("/machines", response_class=HTMLResponse)
async def machines_page(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
    toast: str | None = None,
) -> HTMLResponse:
    today = clock.today()
    uptime = UptimeService(session, clock)
    cards = [
        MachineCard(
            machine=machine,
            uptime=await uptime.daily(machine, today - timedelta(days=UPTIME_DAYS - 1), today),
            last_check=await tasks.last_inspection(machine.id),
        )
        for machine in await MachineRepository(session).list_active()
    ]
    return await admin_page(
        request,
        session,
        "admin/machines.html",
        tab="home",
        back="/app/admin",
        machines=cards,
        toast=toast,
    )


@router.post("/machines/{machine_id}/settings", response_class=HTMLResponse)
async def save_machine_settings(
    request: Request,
    machine_id: int,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
    launched_on: Annotated[date | None, Form()] = None,
    purchase_cost: Annotated[str, Form()] = "",
    vendista_terminal_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    machine = await session.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")
    try:
        cost = Decimal(purchase_cost.replace(" ", "").replace(",", ".")) if purchase_cost else None
    except InvalidOperation as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Стоимость указана неверно"
        ) from exc

    machine.launched_on = launched_on or machine.launched_on
    if cost is not None and cost > 0:
        machine.purchase_cost = cost
    machine.vendista_terminal_id = vendista_terminal_id.strip() or None
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Этот терминал уже привязан к другому силомеру"
        ) from exc
    return await machines_page(request, admin, session, clock, tasks, toast="Сохранено")


@router.post("/vendista/import", response_class=HTMLResponse)
async def import_vendista(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
    export: Annotated[UploadFile, File()],
) -> HTMLResponse:
    data = await export.read()
    try:
        result = await VendistaImporter(session, clock).run(read_transactions(data))
    except VendistaExportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    loaded = [m for m in result.machines if m.payments]
    if not loaded:
        toast = "Нечего загружать: проверьте ID терминалов у силомеров"
    else:
        toast = "Загружено: " + ", ".join(f"{m.machine} {rub(m.amount)}" for m in loaded)
    return await machines_page(request, admin, session, clock, tasks, toast=toast)


@router.post("/machines/{machine_id}/{state}", response_class=HTMLResponse)
async def set_machine_state(
    request: Request,
    machine_id: int,
    state: str,
    admin: AdminUser,
    session: SessionDep,
    clock: ClockDep,
    tasks: TasksDep,
) -> HTMLResponse:
    machine = await session.get(Machine, machine_id)
    if machine is None or state not in {"broken", "fixed"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Силомер не найден")
    if state == "broken":
        machine.broken_since = machine.broken_since or clock.now()
        toast = "Проверки по аппарату на паузе"
    else:
        machine.broken_since = None
        await tasks.schedule_inspections()
        toast = "Силомер снова в работе"
    await session.flush()
    return await machines_page(request, admin, session, clock, tasks, toast=toast)


@router.get("/team", response_class=HTMLResponse)
async def team_page(
    request: Request, _: AdminUser, session: SessionDep, users: UsersDep, toast: str | None = None
) -> HTMLResponse:
    return await admin_page(
        request,
        session,
        "admin/team.html",
        tab="home",
        back="/app/admin",
        users=await users.list_all(),
        toast=toast,
    )


@router.post("/team/{user_id}/{action}", response_class=HTMLResponse)
async def change_access(
    request: Request,
    user_id: int,
    action: str,
    admin: AdminUser,
    session: SessionDep,
    users: UsersDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
) -> HTMLResponse:
    user: User | None = await users.get(user_id)
    if user is None or action not in {"allow", "revoke"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    try:
        await users.set_access(user, active=action == "allow")
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Админа нельзя убрать") from exc

    if action == "allow":
        background.add_task(
            notifier.send,
            [user.telegram_id],
            "✅ Доступ открыт! Отправьте /start, чтобы открыть приложение.",
        )
        toast = f"{user.name} теперь в команде"
    else:
        toast = f"Доступ для {user.name} закрыт"
    return await team_page(request, admin, session, users, toast=toast)
