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
from app.db.models import DailyRevenue, Location, Machine, PaymentAlert, Task, User
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


async def test_init_data_header_survives_clouds_that_drop_authorization(
    client: httpx.AsyncClient,
) -> None:
    headers = {"X-Telegram-Init-Data": make_init_data(WORKER_TG), "HX-Request": "true"}
    assert (await client.get("/app/service", headers=headers)).status_code == 200


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

    answers = {item.key: "yes" for item in CHECKLIST} | {
        "machine": "no",
        "took_bills": "no",
        "took_coins": "no",
    }
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
        "/app/admin/finance",
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


async def report(client: httpx.AsyncClient, machine_id: int, **extra: str) -> httpx.Response:
    form = {item.key: "yes" for item in CHECKLIST} | {"took_bills": "no", "took_coins": "no"}
    return await client.post(
        f"/app/service/machines/{machine_id}/report", data=form | extra, headers=as_user(WORKER_TG)
    )


async def test_cash_goes_from_machine_to_bank(
    app: FastAPI, client: httpx.AsyncClient, db: Database
) -> None:
    from app.db.models import Encashment, TelemetrySale

    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None
        machine_id = machine.id
        session.add(
            TelemetrySale(
                id="s1",
                machine_id=machine_id,
                sold_at=datetime(2026, 10, 20, 15, tzinfo=TZ),
                bill=Decimal("3000"),
                coin=Decimal("0"),
                card=Decimal("0"),
            )
        )
    ledger = await client.post(
        "/app/admin/finance/ledger",
        data={"opened_on": "2026-10-01", "bank_opening": "10 000"},
        headers=as_user(ADMIN_TG),
    )
    assert ledger.status_code == 200

    assert (await report(client, machine_id, took_bills="yes")).status_code == 200
    async with db.session() as session:
        encashment = await session.scalar(select(Encashment))
        assert encashment is not None and encashment.expected_bills == Decimal("3000")
        count_task = await session.scalar(select(Task).where(Task.kind == TaskKind.COUNT_CASH))
        assert count_task is not None and count_task.due_on is None
        encashment_id, count_task_id = encashment.id, count_task.id

    page = await client.get(f"/app/service/tasks/{count_task_id}", headers=as_user(WORKER_TG))
    assert "Сумма купюр" in page.text and "Сумма монет" not in page.text
    counted = await client.post(
        f"/app/service/cash/{encashment_id}/count",
        data={"bills": "2900"},
        headers=as_user(WORKER_TG),
    )
    assert counted.status_code == 200 and "Внести 2 900 ₽" in counted.text
    assert "ожидалось 3 000 ₽" in notifier(app).sent[-1][1]

    deposited = await client.post(
        f"/app/service/cash/{encashment_id}/deposit",
        data={"amount": "2900", "deposited_on": "2026-10-21"},
        headers=as_user(WORKER_TG),
    )
    assert deposited.status_code == 200

    finance = await client.get("/app/admin/finance", headers=as_user(ADMIN_TG))
    # 10 000 opening plus the deposited cash; no card takings or payouts yet.
    assert "12 900 ₽" in finance.text and "в банке" in finance.text


async def test_counted_cash_keeps_its_report(client: httpx.AsyncClient, db: Database) -> None:
    from app.db.models import Encashment

    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None
        machine_id = machine.id
    await report(client, machine_id, took_coins="yes")
    async with db.session() as session:
        encashment = await session.scalar(select(Encashment))
        assert encashment is not None
        encashment_id, report_id = encashment.id, encashment.report_id
    await client.post(
        f"/app/service/cash/{encashment_id}/count",
        data={"coins": "500"},
        headers=as_user(WORKER_TG),
    )
    refused = await client.post(
        f"/app/service/reports/{report_id}/delete", headers=as_user(WORKER_TG)
    )
    assert refused.status_code == 409


async def test_report_can_be_deleted_and_commented(client: httpx.AsyncClient, db: Database) -> None:
    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None
        machine_id = machine.id
    await report(client, machine_id, comment="Грязный")
    async with db.session() as session:
        filed = await session.scalar(
            select(Task).where(Task.kind == TaskKind.INSPECTION, Task.comment.is_not(None))
        )
        assert filed is not None
        report_id = filed.id

    edited = await client.post(
        f"/app/admin/reports/{report_id}/comment",
        data={"comment": "Грязный, помыли"},
        headers=as_user(ADMIN_TG),
    )
    assert "Грязный, помыли" in edited.text

    deleted = await client.post(
        f"/app/service/reports/{report_id}/delete", headers=as_user(WORKER_TG)
    )
    assert (
        deleted.status_code == 200
        and f"/app/machines/{machine_id}" in deleted.headers["HX-Location"]
    )
    async with db.session() as session:
        assert await session.get(Task, report_id) is None


async def test_payout_and_cash_history(client: httpx.AsyncClient) -> None:
    paid = await client.post(
        "/app/admin/finance/payouts",
        data={"amount": "50000", "paid_on": "2026-01-10", "recipient": "Артём", "note": "за 2025"},
        headers=as_user(ADMIN_TG),
    )
    assert paid.status_code == 200 and "Артём · 50 000 ₽" in paid.text

    history = await client.post(
        "/app/admin/cash-history",
        data={
            "machine_id": "1",
            "first_day": "2024-05-01",
            "last_day": "2024-05-31",
            "coins": "3 100",
            "bills": "6200",
        },
        headers=as_user(ADMIN_TG),
    )
    assert history.status_code == 200 and "9 300 ₽" in history.text


async def test_broken_machine_is_loud_for_everyone(client: httpx.AsyncClient, db: Database) -> None:
    async with db.session() as session:
        machine = await session.scalar(select(Machine))
        assert machine is not None
        machine.broken_since = datetime(2026, 10, 18, 9, tzinfo=TZ)
    service = await client.get("/app/service", headers=as_user(WORKER_TG))
    admin = await client.get("/app/admin", headers=as_user(ADMIN_TG))
    for page in (service, admin):
        assert "стоит 3 дня" in page.text and "Чините как можно скорее" in page.text
    assert "Починил — заполнить отчёт" in service.text


async def test_export_for_ai(app: FastAPI, client: httpx.AsyncClient) -> None:
    import io
    import zipfile

    response = await client.post("/app/admin/export", headers=as_user(ADMIN_TG))
    assert response.status_code == 200

    ((chat_id, filename, data),) = notifier(app).documents
    assert chat_id == ADMIN_TG and filename.endswith(".zip")
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    assert {"machines.csv", "daily_revenue.csv", "monthly_summary.csv", "ПРОМТ_ДЛЯ_ИИ.txt"} <= names
    assert "attachments.csv" not in names
    users = archive.read("users.csv").decode()
    assert str(ADMIN_TG) not in users and "telegram_id" not in users
    # The prompt also arrives as a message ready to copy.
    assert "аналитик" in notifier(app).sent[-1][1]


async def test_iphone_widget(app: FastAPI, client: httpx.AsyncClient, db: Database) -> None:
    assert (await client.get("/widget/not-a-token")).status_code == 404

    sent = await client.post("/app/service/widget", headers=as_user(WORKER_TG))
    assert sent.status_code == 200
    ((chat_id, filename, script),) = notifier(app).documents
    assert chat_id == WORKER_TG and filename.endswith(".js")
    async with db.session() as session:
        worker = await session.scalar(select(User).where(User.telegram_id == WORKER_TG))
        assert worker is not None and worker.widget_token
        token = worker.widget_token
        assert token in script.decode()
        machine = await session.scalar(select(Machine))
        assert machine is not None
        machine.broken_since = datetime(2026, 10, 19, 9, tzinfo=TZ)
        session.add(Task(kind=TaskKind.CUSTOM, title="Подшить грушу", due_on=date(2026, 10, 23)))

    data = (await client.get(f"/widget/{token}")).json()
    assert data["alerts"] == [{"level": "down", "text": "«Пушкина» стоит 2 дня (сломан)"}]
    assert data["down"] == [
        {"machine": "Пушкина", "reason": "сломан", "days": 2, "days_word": "дня"}
    ]
    assert data["checks"] == [] and data["machines"] == ["Пушкина"]

    async with db.session() as session:
        pushkina = await session.scalar(select(Machine))
        assert pushkina is not None
        dinamo = Machine(name="Динамо", purchase_cost=Decimal(1))
        session.add(dinamo)
        await session.flush()
        raised = datetime(2026, 10, 20, 9, tzinfo=TZ)
        for machine, channel in [
            (dinamo, PaymentChannel.COIN),
            (dinamo, PaymentChannel.CARD),
            (pushkina, PaymentChannel.BILL),
        ]:
            session.add(
                PaymentAlert(
                    machine_id=machine.id,
                    channel=channel,
                    raised_at=raised,
                    recent_sales=30,
                    recent_hits=0,
                    quiet_days=2,
                )
            )
    data = (await client.get(f"/widget/{token}")).json()
    # The broken machine's bill acceptor isn't worth a word while it stands idle.
    assert data["checks"] == [{"machine": "Динамо", "devices": ["монетоприёмник", "терминал"]}]
    assert data["machines"] == ["Динамо", "Пушкина"]
    assert data["next_task"] == {"title": "Подшить грушу", "when": "23 октября", "overdue": False}


async def test_loading_video_once_a_day(app: FastAPI, client: httpx.AsyncClient) -> None:
    first = await client.get("/app/service", headers=as_user(WORKER_TG))
    again = await client.get("/app/service", headers=as_user(WORKER_TG))
    assert "splash.mp4" in first.text and "splash.mp4" not in again.text

    app.state.clock.shift(days=1)
    tomorrow = await client.get("/app/service", headers=as_user(WORKER_TG))
    assert "splash.mp4" in tomorrow.text
    # Admins looking at the service screen never get it.
    admin = await client.get("/app/service", headers=as_user(ADMIN_TG))
    assert "splash.mp4" not in admin.text
