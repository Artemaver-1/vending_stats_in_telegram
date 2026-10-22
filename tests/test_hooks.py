import io
import zipfile
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
import pytest
from aiogram.types import BufferedInputFile
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.api.main import create_app
from app.config import Settings
from app.db import Database
from app.services.file_drop import FileDrop
from app.services.notifications import TelegramNotifier
from app.worker.jobs import ServiceJobs
from tests.helpers import BOT_TOKEN, TZ, FakeNotifier, FixedClock

SECRET = "hook-secret"


class FakeDispatcher:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def feed_webhook_update(self, bot: object, update: dict[str, Any]) -> None:
        self.updates.append(update)


@pytest.fixture
async def client(db: Database) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    settings = Settings(
        bot_token=SecretStr(BOT_TOKEN), hook_secret=SecretStr(SECRET), _env_file=None
    )
    app = create_app(settings)
    clock = FixedClock(datetime(2026, 10, 21, 12, tzinfo=TZ))
    app.state.db = db
    app.state.notifier = FakeNotifier()
    app.state.clock = clock
    app.state.bot = object()
    app.state.dispatcher = FakeDispatcher()
    app.state.service_jobs = ServiceJobs(db, app.state.notifier, clock)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield app, http


async def test_webhook_needs_telegrams_secret(client: tuple[FastAPI, httpx.AsyncClient]) -> None:
    app, http = client
    update = {"update_id": 1}
    assert (await http.post("/telegram/webhook", json=update)).status_code == 404
    wrong = {"X-Telegram-Bot-Api-Secret-Token": "guess"}
    assert (await http.post("/telegram/webhook", json=update, headers=wrong)).status_code == 404
    right = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
    assert (await http.post("/telegram/webhook", json=update, headers=right)).status_code == 200
    assert app.state.dispatcher.updates == [update]


async def test_timers_run_jobs_by_secret_path(client: tuple[FastAPI, httpx.AsyncClient]) -> None:
    _, http = client
    assert (await http.post("/jobs/guess/reminders")).status_code == 404
    assert (await http.post(f"/jobs/{SECRET}/nothing")).status_code == 404
    done = await http.post(f"/jobs/{SECRET}/reminders")
    assert done.json() == {"job": "reminders", "result": "ok"}
    # Without SmartVend configured the half-hourly run still checks payments and inspections.
    assert (await http.post(f"/jobs/{SECRET}/telemetry")).json()["result"] == "ok"


async def test_endpoints_stay_closed_without_a_secret(db: Database) -> None:
    app = create_app(Settings(bot_token=SecretStr(BOT_TOKEN), _env_file=None))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.post("/jobs/anything/reminders")).status_code == 404
        assert (await http.post("/telegram/webhook", json={})).status_code == 404


def test_hosted_database_url_wins() -> None:
    settings = Settings(
        bot_token=SecretStr(BOT_TOKEN),
        DATABASE_URL="postgresql://postgres.abc:pa))ss%40@pooler.example.com:5432/postgres",
        _env_file=None,
    )
    url = make_url(settings.database_url)
    assert (url.drivername, url.password, url.host) == (
        "postgresql+asyncpg",
        "pa))ss@",
        "pooler.example.com",
    )


class RecordingBot:
    def __init__(self) -> None:
        self.documents: list[tuple[int, object]] = []

    async def send_document(self, chat_id: int, document: object, caption: str) -> None:
        self.documents.append((chat_id, document))


async def test_big_files_go_to_telegram_as_links(
    client: tuple[FastAPI, httpx.AsyncClient], db: Database
) -> None:
    app, http = client
    drop = FileDrop(db, "https://cloud.example")
    app.state.file_drop = drop
    bot = RecordingBot()
    notifier = TelegramNotifier(bot, drop)  # type: ignore[arg-type]

    await notifier.send_document(1, "small.js", b"x" * 100, "")
    await notifier.send_document(1, "vending.sql.gz", b"y" * 50_000, "")
    small, big = (document for _, document in bot.documents)
    assert isinstance(small, BufferedInputFile)
    # Telegram only fetches ZIP or PDF documents by link, so the dump gets wrapped.
    assert isinstance(big, str) and big.endswith("/vending.sql.gz.zip")

    served = await http.get(big.removeprefix("https://cloud.example"))
    assert served.status_code == 200
    with zipfile.ZipFile(io.BytesIO(served.content)) as archive:
        assert archive.read("vending.sql.gz") == b"y" * 50_000
    assert (await http.get("/files/" + "0" * 32 + "/x.zip")).status_code == 404
