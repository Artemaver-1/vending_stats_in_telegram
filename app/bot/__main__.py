import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from app.bot.handlers import build_router
from app.bot.middlewares import AccessMiddleware, DatabaseMiddleware
from app.bot.webapp_link import WebAppLink
from app.config import Settings, get_settings
from app.db import Database
from app.services.notifications import TelegramNotifier
from app.services.staff import UserService

logger = logging.getLogger(__name__)

LINK_CHECK_SECONDS = 120


def build_dispatcher(bot: Bot, db: Database, webapp: WebAppLink) -> Dispatcher:
    dp = Dispatcher(webapp=webapp)
    dp.update.outer_middleware(DatabaseMiddleware(db))
    dp.update.outer_middleware(AccessMiddleware(TelegramNotifier(bot)))
    dp.include_router(build_router())
    return dp


async def keep_menu_buttons_fresh(bot: Bot, db: Database, webapp: WebAppLink) -> None:
    """The quick tunnel gets a new address on every restart; follow it."""
    while True:
        if await webapp.refresh():
            logger.info("Mini App is now at %s", webapp.url)
            await publish_address(bot, webapp)
            async with db.session() as session:
                users = [u for u in await UserService(session).list_all() if u.is_active]
            await webapp.apply(bot, users)
        # Until the tunnel reports its address, ask often so /start works soon after boot.
        await asyncio.sleep(LINK_CHECK_SECONDS if webapp.url else 5)


async def publish_address(bot: Bot, webapp: WebAppLink) -> None:
    """The iPhone widget can't ask the bot, but it can read the bot's public profile page,
    so the current address goes into the short description."""
    if webapp.url is None:
        return
    base = webapp.url.removesuffix("/app")
    with contextlib.suppress(TelegramAPIError):
        await bot.set_my_short_description(f"Задачи и статистика силомеров · {base}")


async def bootstrap_admins(db: Database, settings: Settings) -> None:
    if not settings.admin_ids:
        logger.warning("ADMIN_IDS is empty, nobody can let people into the bot")
    async with db.session() as session:
        await UserService(session).ensure_admins(settings.admin_ids)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database(settings.database_url)
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
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
