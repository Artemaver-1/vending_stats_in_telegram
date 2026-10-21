import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot.handlers import build_router
from app.bot.middlewares import AccessMiddleware, DatabaseMiddleware
from app.clock import Clock
from app.config import Settings, get_settings
from app.db import Database

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="month", description="Финансы за месяц"),
    BotCommand(command="payback", description="Окупаемость"),
    BotCommand(command="help", description="Что умеет бот"),
]


def build_dispatcher(settings: Settings, db: Database) -> Dispatcher:
    dp = Dispatcher(clock=Clock(settings.tz))
    dp.update.outer_middleware(AccessMiddleware(settings.allowed_user_ids))
    dp.update.outer_middleware(DatabaseMiddleware(db))
    dp.include_router(build_router())
    return dp


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.allowed_user_ids:
        logger.warning("ALLOWED_USER_IDS is empty, nobody will be able to use the bot")

    db = Database(settings.database_url)
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(settings, db)

    try:
        await bot.set_my_commands(COMMANDS)
        # Updates sent while the machine was off are kept by Telegram for 24 hours;
        # not dropping them means everything typed offline gets processed on startup.
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
