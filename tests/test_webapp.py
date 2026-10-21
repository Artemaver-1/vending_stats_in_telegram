import re
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from app.api.main import create_app
from app.config import Settings
from app.db import Database
from app.db.models import Location, Machine, PurchaseRequest, Task, User
from app.domain.enums import TaskKind, UserRole
from app.domain.inspection import CHECKLIST
from tests.helpers import BOT_TOKEN, TZ, FakeNotifier, FixedClock, make_init_data

ADMIN_TG, WORKER_TG, STRANGER_TG = 1001, 2002, 3003


@pytest.fixture
async def app(db: Database) -> FastAPI:
    application = create_app(Settings(bot_token=SecretStr(BOT_TOKEN), _env_file=None))  # type: ignore[call-arg]
    application.state.db = db
    application.state.notifier = FakeNotifier()
    application.state.clock = FixedClock(datetime(2026, 10, 21, 12, tzinfo=TZ))

    async with db.session() as session:
        location = Location(name="Пушкина")
        session.add(location)
        await session.flush()
        session.add_all(
            [
                Machine(name="Пушкина", location_id=location.id, purchase_cost=Decimal("320000")),
                User(telegram_id=ADMIN_TG, name="Артём", role=UserRole.ADMIN, is_active=True),
                User(telegram_id=WORKER_TG, name="Вася", role=UserRole.WORKER, is_active=True),
                User(telegram_id=STRANGER_TG, name="Кто-то", is_active=False),
            ]
        )
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def as_user(telegram_id: int) -> dict[str, str]:
    return {"Authorization": f"tma {make_init_data(telegram_id)}", "HX-Request": "true"}


def notifier(app: FastAPI) -> FakeNotifier:
    fake: FakeNotifier = app.state.notifier
    return fake


async def test_shell_is_public_but_screens_are_not(client: httpx.AsyncClient) -> None:
    assert (await client.get("/app")).status_code == 200
    assert (await client.get("/app/service", headers={"HX-Request": "true"})).status_code == 401
    # A reload of a screen URL lands back on the shell instead of a bare fragment.
    reload = await client.get("/app/admin")
    assert (reload.status_code, reload.headers["location"]) == (307, "/app")
    assert (await client.get("/app/service", headers=as_user(STRANGER_TG))).status_code == 403
    assert (await client.get("/app/admin", headers=as_user(WORKER_TG))).status_code == 403
    assert (await client.get("/finance/payback", headers=as_user(WORKER_TG))).status_code == 403


async def test_home_routes_by_role(client: httpx.AsyncClient) -> None:
    admin = await client.get("/app/home", headers=as_user(ADMIN_TG))
    worker = await client.get("/app/home", headers=as_user(WORKER_TG))
    assert '"/app/admin"' in admin.headers["HX-Location"]
    assert '"/app/service"' in worker.headers["HX-Location"]


async def test_worker_inspection_reports_broken_machine(
    app: FastAPI, client: httpx.AsyncClient, db: Database
) -> None:
    async with db.session() as session:
        from app.services.tasks import TaskService

        (task,) = await TaskService(session, app.state.clock).schedule_inspections()
        task_id = task.id

    home = await client.get("/app/service", headers=as_user(WORKER_TG))
    assert "Обслуживание силомеров" in home.text
    assert "работник" not in home.text.lower()
    assert "Проверка силомера «Пушкина»" in home.text

    form = {item.key: "yes" for item in CHECKLIST} | {"machine": "no", "order": "Груша"}
    response = await client.post(
        f"/app/service/tasks/{task_id}/inspection", data=form, headers=as_user(WORKER_TG)
    )
    assert response.status_code == 200
    assert "toast" in response.headers["HX-Trigger"]
    assert "Починил — проверить" in response.text

    ((recipients, text, _),) = notifier(app).sent
    assert recipients == [ADMIN_TG]
    assert "силомер не работает" in text and "Груша" in text

    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None and machine.is_broken
        assert await session.scalar(select(PurchaseRequest.text)) == "Груша"


async def test_admin_creates_task_with_qr_for_worker(
    app: FastAPI, client: httpx.AsyncClient, db: Database
) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    response = await client.post(
        "/app/admin/tasks",
        data={"title": "Получить датчик в СДЭК", "due_on": "2026-10-23"},
        files={"attachment": ("qr.png", png, "image/png")},
        headers=as_user(ADMIN_TG),
    )
    assert response.status_code == 200
    assert "Получить датчик в СДЭК" in response.text

    ((recipients, text, with_photo),) = notifier(app).sent
    assert recipients == [WORKER_TG] and with_photo
    assert "Новая задача" in text

    async with db.session() as session:
        task = await session.scalar(select(Task).where(Task.kind == TaskKind.CUSTOM))
        assert task is not None
        task_id = task.id

    page = await client.get(f"/app/service/tasks/{task_id}", headers=as_user(WORKER_TG))
    link = re.search(r'src="(/app/attachments/[^"]+)"', page.text)
    assert link is not None
    image = await client.get(link.group(1).replace("&amp;", "&"))
    assert image.status_code == 200 and image.content == png
    assert (await client.get("/app/attachments/1?exp=1&sig=x")).status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/app/admin",
        "/app/admin/tasks",
        "/app/admin/tasks?view=done",
        "/app/admin/tasks/new",
        "/app/admin/purchases",
        "/app/admin/economics",
        "/app/admin/economics?month=2026-09",
        "/app/admin/rent",
        "/app/admin/rent/contracts/new",
        "/app/admin/machines",
        "/app/admin/team",
    ],
)
async def test_admin_screens_render(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path, headers=as_user(ADMIN_TG))
    assert response.status_code == 200, response.text
    assert 'class="tabbar"' in response.text


async def test_admin_adds_rent_contract_and_expense(client: httpx.AsyncClient) -> None:
    contract = await client.post(
        "/app/admin/rent/contracts",
        data={
            "location_id": "1",
            "rent_type": "fixed",
            "amount": "12000",
            "payment_day": "15",
            "valid_from": "2026-08-01",
        },
        headers=as_user(ADMIN_TG),
    )
    assert contract.status_code == 200
    assert contract.text.count("Оплачено") == 2  # August and September accrued

    expense = await client.post(
        "/app/admin/expenses",
        data={"amount": "1 500,50", "spent_on": "2026-10-10", "category": "parts"},
        headers=as_user(ADMIN_TG),
    )
    assert expense.status_code == 200
    assert "1 500,50 ₽" in expense.text


async def test_admin_lets_new_person_in(
    app: FastAPI, client: httpx.AsyncClient, db: Database
) -> None:
    team = await client.get("/app/admin/team", headers=as_user(ADMIN_TG))
    assert "Просят доступ" in team.text and "Кто-то" in team.text

    async with db.session() as session:
        stranger = await session.scalar(select(User).where(User.telegram_id == STRANGER_TG))
        assert stranger is not None

    response = await client.post(f"/app/admin/team/{stranger.id}/allow", headers=as_user(ADMIN_TG))
    assert response.status_code == 200
    assert (await client.get("/app/service", headers=as_user(STRANGER_TG))).status_code == 200
    assert notifier(app).sent[0][0] == [STRANGER_TG]
