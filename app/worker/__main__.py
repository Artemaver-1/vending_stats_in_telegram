import asyncio
import logging
import signal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.clock import Clock
from app.config import get_settings
from app.db import Database
from app.integrations.smartvend import SmartVendClient
from app.services.notifications import TelegramNotifier
from app.worker.jobs import ServiceJobs, TelemetryJobs

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if settings.smartvend_api_key is None:
        raise SystemExit("SMARTVEND_API_KEY is not set")

    clock = Clock(settings.tz)
    db = Database(settings.database_url)
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    client = SmartVendClient(
        settings.smartvend_api_key.get_secret_value(), settings.smartvend_base_url
    )
    notifier = TelegramNotifier(bot)
    jobs = TelemetryJobs(settings, db, client, notifier, clock)
    service = ServiceJobs(db, notifier, clock)

    # Both jobs also fire right away, so a host that was switched off catches up on boot.
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    job_defaults = {"max_instances": 1, "coalesce": True, "next_run_time": clock.now()}
    scheduler.add_job(jobs.sync_connectivity, "interval", minutes=5, **job_defaults)
    scheduler.add_job(jobs.sync_sales, "interval", minutes=30, **job_defaults)
    scheduler.add_job(service.schedule_inspections, "interval", hours=1, **job_defaults)
    # Reminders go out once a day; checking hourly from 10 to 21 still catches days
    # when the computer is switched on late.
    scheduler.add_job(
        service.send_reminders, "cron", hour="10-21", minute=5, max_instances=1, coalesce=True
    )
    scheduler.start()
    logger.info("Worker started")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await client.close()
        await bot.session.close()
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
