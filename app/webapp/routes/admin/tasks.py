from datetime import date
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

from app.api.deps import SessionDep
from app.domain.enums import TaskStatus, UserRole
from app.repositories import MachineRepository
from app.services.notifications import Messages, Photo
from app.services.tasks import NewAttachment
from app.webapp.auth import AdminUser
from app.webapp.deps import NotifierDep, TasksDep, UsersDep
from app.webapp.routes.admin.common import admin_page, optional_int

router = APIRouter(prefix="/app/admin")

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    tasks: TasksDep,
    view: str = "open",
    toast: str | None = None,
) -> HTMLResponse:
    task_status = TaskStatus.DONE if view == "done" else TaskStatus.OPEN
    return await admin_page(
        request,
        session,
        "admin/tasks.html",
        tab="tasks",
        view="done" if task_status is TaskStatus.DONE else "open",
        tasks=await tasks.with_status(task_status),
        toast=toast,
    )


@router.get("/tasks/new", response_class=HTMLResponse)
async def new_task_form(request: Request, _: AdminUser, session: SessionDep) -> HTMLResponse:
    return await admin_page(
        request,
        session,
        "admin/task_form.html",
        tab="tasks",
        back="/app/admin/tasks",
        machines=await MachineRepository(session).list_active(),
    )


@router.post("/tasks", response_class=HTMLResponse)
async def create_task(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    tasks: TasksDep,
    users: UsersDep,
    notifier: NotifierDep,
    background: BackgroundTasks,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    due_on: Annotated[date, Form()],
    description: Annotated[str, Form()] = "",
    machine_id: Annotated[str, Form()] = "",
    attachment: Annotated[UploadFile | None, File()] = None,
) -> HTMLResponse:
    new_attachment = None
    if attachment is not None and attachment.filename:
        data = await attachment.read()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 5 МБ")
        new_attachment = NewAttachment(
            attachment.filename, attachment.content_type or "application/octet-stream", data
        )

    task = await tasks.create(
        title=title,
        description=description,
        due_on=due_on,
        machine_id=optional_int(machine_id),
        author=admin,
        attachment=new_attachment,
    )
    await session.commit()

    recipients = await users.telegram_ids(UserRole.WORKER)
    photo = None
    if new_attachment and new_attachment.content_type.startswith("image/"):
        photo = Photo(new_attachment.filename, new_attachment.data)
    background.add_task(notifier.send, recipients, Messages.new_task(task), photo=photo)

    return await tasks_page(request, admin, session, tasks, toast="Задача поставлена")


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_page(
    request: Request, task_id: int, _: AdminUser, session: SessionDep, tasks: TasksDep
) -> HTMLResponse:
    task = await tasks.get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    return await admin_page(
        request, session, "admin/task.html", tab="tasks", task=task, back="/app/admin/tasks"
    )


@router.post("/tasks/{task_id}/cancel", response_class=HTMLResponse)
async def cancel_task(
    request: Request, task_id: int, admin: AdminUser, session: SessionDep, tasks: TasksDep
) -> HTMLResponse:
    task = await tasks.get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    await tasks.cancel(task, admin)
    return await tasks_page(request, admin, session, tasks, toast="Задача отменена")
