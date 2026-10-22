"""Entry points of the serverless deployment: Telegram's webhook and the cloud timers.

Both are closed unless HOOK_SECRET is set. Telegram sends the secret in a header; the
timers can't set headers, so for them it's part of the path.
"""

import logging
import mimetypes
import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.bot.setup import bootstrap_admins, point_team_at, publish_address
from app.config import Settings
from app.domain.enums import UserRole
from app.services.backup import BackupError, DatabaseBackup
from app.services.staff import UserService

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)


def _require(settings: Settings, given: str) -> None:
    expected = settings.hook_secret
    if expected is None or not secrets.compare_digest(given, expected.get_secret_value()):
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get("/files/{file_id}/{filename}")
async def outgoing_file(file_id: str, filename: str, request: Request) -> Response:
    drop = getattr(request.app.state, "file_drop", None)
    item = await drop.get(file_id) if drop is not None else None
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    media_type = mimetypes.guess_type(item.filename)[0] or "application/octet-stream"
    return Response(item.data, media_type=media_type)


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    state = request.app.state
    _require(state.settings, request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""))
    await state.dispatcher.feed_webhook_update(state.bot, await request.json())
    return Response(status_code=status.HTTP_200_OK)


@router.post("/jobs/{secret}/{name}", response_model=None)
async def run_job(secret: str, name: str, request: Request) -> dict[str, Any] | JSONResponse:
    state = request.app.state
    _require(state.settings, secret)
    jobs = {
        "telemetry": _telemetry,
        "reminders": _reminders,
        "backup": _backup,
        "setup": _setup,
    }
    if name not in jobs:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    try:
        result = await jobs[name](request)
    except Exception as exc:
        # The cloud keeps no logs for free, so the reason goes back to whoever called.
        logger.exception("Job %s failed", name)
        detail = {"job": name, "error": f"{type(exc).__name__}: {exc}"}
        return JSONResponse(detail, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.info("Job %s: %s", name, result)
    return {"job": name, "result": result}


async def _telemetry(request: Request) -> str:
    """Connection, sales, payment methods and inspections, every half hour."""
    state = request.app.state
    failure = None
    if getattr(state, "telemetry", None) is not None:
        failure = await state.telemetry.sync_connectivity() or await state.telemetry.sync_sales()
    # Payments are checked on the sales already stored even if SmartVend is down.
    await state.service_jobs.watch_payments()
    await state.service_jobs.schedule_inspections()
    if getattr(state, "file_drop", None) is not None:
        await state.file_drop.purge()
    return failure or "ok"


async def _reminders(request: Request) -> str:
    await request.app.state.service_jobs.send_reminders()
    return "ok"


async def _backup(request: Request) -> str:
    """Hosted databases on a free plan keep no copies we can download, so every night the
    dump goes to the owners' chat with the bot."""
    state = request.app.state
    async with state.db.session() as session:
        admins = await UserService(session).telegram_ids(UserRole.ADMIN)
    # The night's run belongs to the day that just ended.
    day = state.clock.now() - timedelta(hours=6)
    try:
        dump = await DatabaseBackup(state.settings.database_url).dump()
    except (BackupError, OSError) as exc:
        logger.exception("Backup failed")
        await state.notifier.send(admins, f"⚠️ Резервная копия базы не сделана: {exc}")
        return "failed"
    for chat_id in admins:
        await state.notifier.send_document(
            chat_id,
            f"vending-{day:%Y-%m-%d}.sql.gz",
            dump,
            f"💾 Резервная копия базы за {day:%d.%m.%Y}. Восстановить: распаковать и "
            "передать .sql.gz в scripts/restore.sh",
        )
    return f"{len(dump) // 1024} KB"


async def _setup(request: Request) -> str:
    """Run once after a deploy: points Telegram at the webhook and the team's menu buttons
    at the Mini App."""
    state = request.app.state
    settings: Settings = state.settings
    reach = settings.telegram_reach_url
    if settings.webapp_url is None or reach is None or settings.hook_secret is None:
        return "WEBAPP_URL and HOOK_SECRET are required"
    await bootstrap_admins(state.db, settings)
    bot = state.bot
    await bot.delete_my_commands()
    await bot.set_webhook(
        reach.rstrip("/") + "/telegram/webhook",
        secret_token=settings.hook_secret.get_secret_value(),
        allowed_updates=state.dispatcher.resolve_used_update_types(),
    )
    webapp = state.dispatcher["webapp"]
    await publish_address(bot, webapp)
    await point_team_at(bot, state.db, webapp)
    return "ok"
