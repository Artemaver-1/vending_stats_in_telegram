import re
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from app.api.main import create_app
from app.config import Settings
from app.db import Database
from app.db.models import DailyRevenue, Location, Machine, Task, User
from app.domain.enums import PaymentChannel, RevenueSource, TaskKind, UserRole
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


async def test_worker_report_reaches_admin(
    app: FastAPI, client: httpx.AsyncClient, db: Database
) -> None:
    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None
        machine_id = machine.id

    home = await client.get("/app/service", headers=as_user(WORKER_TG))
    assert "Обслуживание силомеров" in home.text
    assert "работник" not in home.text.lower()
    assert f"/app/service/machines/{machine_id}/report" in home.text

    form_page = await client.get(
        f"/app/service/machines/{machine_id}/report", headers=as_user(WORKER_TG)
    )
    assert "Состояние до визита" in form_page.text
    assert "Терминал безнала (Вендиста) работает?" in form_page.text

    answers = {item.key: "yes" for item in CHECKLIST} | {"machine": "no"}
    response = await client.post(
        f"/app/service/machines/{machine_id}/report",
        data=answers | {"comment": "Груша порвана, надо подшить"},
        headers=as_user(WORKER_TG),
    )
    assert response.status_code == 200
    assert "toast" in response.headers["HX-Trigger"]

    ((recipients, text, _),) = notifier(app).sent
    assert recipients == [ADMIN_TG]
    assert "силомер не работает" in text and "подшить" in text

    feed = await client.get("/app/admin/reports", headers=as_user(ADMIN_TG))
    assert "Инфа от работника" in feed.text
    assert "Груша порвана, надо подшить" in feed.text and "новый" in feed.text
    again = await client.get("/app/admin/reports", headers=as_user(ADMIN_TG))
    assert "новый" not in again.text

    next_form = await client.get(
        f"/app/service/machines/{machine_id}/report", headers=as_user(WORKER_TG)
    )
    assert "Не работает" in next_form.text and "надо подшить" in next_form.text


async def test_refresh_button_runs_sync(app: FastAPI, client: httpx.AsyncClient) -> None:
    class FakeTelemetry:
        calls = 0
        failure: str | None = None

        async def refresh_all(self) -> str | None:
            self.calls += 1
            return self.failure

    fake = FakeTelemetry()
    app.state.telemetry = fake
    response = await client.post("/app/admin/sync", headers=as_user(ADMIN_TG))
    assert response.status_code == 200 and fake.calls == 1
    assert (await client.post("/app/admin/sync", headers=as_user(WORKER_TG))).status_code == 403

    # When SmartVend can't be reached the reason reaches the admin's toast.
    fake.failure = "Сервер SmartVend не отвечает."
    failed = await client.post("/app/admin/sync", headers=as_user(ADMIN_TG))
    assert failed.status_code == 200
    assert "toastError" in failed.headers["HX-Trigger"]


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
        "/app/admin/reports",
        "/app/admin/ofr",
        "/app/admin/ofr?all_time=true",
        "/app/admin/ofr?start=2026-09-01&end=2026-09-30&machine=1",
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


async def test_income_statement_shows_taxes_and_shares(client: httpx.AsyncClient) -> None:
    for category, amount in (("taxes", "600"), ("insurance", "300"), ("connectivity", "250")):
        response = await client.post(
            "/app/admin/expenses",
            data={"amount": amount, "spent_on": "2026-10-10", "category": category},
            headers=as_user(ADMIN_TG),
        )
        assert response.status_code == 200

    page = await client.get(
        "/app/admin/ofr?start=2026-10-01&end=2026-10-21", headers=as_user(ADMIN_TG)
    )
    text = page.text
    for line in (
        "Выручка",
        "Себестоимость",
        "Плата за симкарты",
        "Плата за SmartVend",
        "Работник",
        "Налоги",
        "Страховые взносы",
        "Чистая прибыль",
    ):
        assert line in text
    assert "−1 150 ₽" in text  # nothing earned, everything spent


async def test_service_accounts_share_one_screen(
    app: FastAPI, client: httpx.AsyncClient, db: Database
) -> None:
    second_tg = 4004
    async with db.session() as session:
        session.add(
            User(telegram_id=second_tg, name="Второй", role=UserRole.WORKER, is_active=True)
        )

    created = await client.post(
        "/app/admin/tasks",
        data={"title": "Подшить грушу", "due_on": "2026-10-22"},
        headers=as_user(ADMIN_TG),
    )
    assert created.status_code == 200
    ((recipients, _, _),) = notifier(app).sent
    assert sorted(recipients) == sorted([WORKER_TG, second_tg])

    first = await client.get("/app/service", headers=as_user(WORKER_TG))
    second = await client.get("/app/service", headers=as_user(second_tg))
    assert "Подшить грушу" in first.text and "Подшить грушу" in second.text

    async with db.session() as session:
        task = await session.scalar(select(Task).where(Task.title == "Подшить грушу"))
        assert task is not None
        task_id = task.id
    await client.post(f"/app/service/tasks/{task_id}/done", headers=as_user(second_tg))

    # Whoever closed it, the other account sees the same result.
    after = await client.get("/app/service", headers=as_user(WORKER_TG))
    assert "Недавно сделано" in after.text and "Второй" in after.text


@pytest.mark.parametrize(
    "query",
    ["", "?view=weeks", "?view=year", "?view=year&year=2025", "?view=month&year=2026&month=9"],
)
async def test_machine_screen_is_open_to_the_service_team(
    client: httpx.AsyncClient, query: str
) -> None:
    response = await client.get(f"/app/machines/1{query}", headers=as_user(WORKER_TG))
    assert response.status_code == 200, response.text
    assert "Выручка за 30 дней" in response.text
    # Revenue is fine to show; profit and rent stay in the admin panel.
    assert "прибыль" not in response.text.lower()
    assert "аренд" not in response.text.lower()


async def test_worker_home_shows_takings_per_machine(
    client: httpx.AsyncClient, db: Database
) -> None:
    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None
        session.add(
            DailyRevenue(
                machine_id=machine.id,
                day=date(2026, 10, 15),
                channel=PaymentChannel.COIN,
                amount=Decimal("740"),
                source=RevenueSource.TELEMETRY,
            )
        )
    home = await client.get("/app/service", headers=as_user(WORKER_TG))
    assert "740 ₽" in home.text and "/app/machines/" in home.text
