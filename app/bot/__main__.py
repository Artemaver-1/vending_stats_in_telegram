import asyncio
import contextlib
import logging

from aiogram import Bot

from app.bot.client import make_bot
from app.bot.setup import bootstrap_admins, build_dispatcher, point_team_at, publish_address
from app.bot.webapp_link import WebAppLink
from app.config import get_settings
from app.db import Database

logger = logging.getLogger(__name__)

LINK_CHECK_SECONDS = 120


async def keep_menu_buttons_fresh(bot: Bot, db: Database, webapp: WebAppLink) -> None:
    """The quick tunnel gets a new address on every restart; follow it."""
    while True:
        if await webapp.refresh():
            logger.info("Mini App is now at %s", webapp.url)
            await publish_address(bot, webapp)
            await point_team_at(bot, db, webapp)
        # Until the tunnel reports its address, ask often so /start works soon after boot.
        await asyncio.sleep(LINK_CHECK_SECONDS if webapp.url else 5)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database(settings.database_url)
    bot = make_bot(settings)
    webapp = WebAppLink(settings.webapp_url, settings.tunnel_metrics_url)
    dp = build_dispatcher(bot, db, webapp)
    await bootstrap_admins(db, settings)

    link_task = asyncio.create_task(keep_menu_buttons_fresh(bot, db, webapp))
    try:
        # No commands in the menu: the chat button opening the Mini App is the only control.
        await bot.delete_my_commands()
        # Updates sent while the machine was off are kept by Telegram for 24 hours;
        # not dropping them means everything typed offline gets processed on startup.
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        link_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await link_task
        await bot.session.close()
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
