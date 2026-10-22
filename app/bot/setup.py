import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError

from app.bot.handlers import build_router
from app.bot.middlewares import AccessMiddleware, DatabaseMiddleware
from app.bot.webapp_link import WebAppLink
from app.config import Settings
from app.db import Database
from app.services.notifications import TelegramNotifier
from app.services.staff import UserService

logger = logging.getLogger(__name__)


def build_dispatcher(bot: Bot, db: Database, webapp: WebAppLink) -> Dispatcher:
    dp = Dispatcher(webapp=webapp)
    dp.update.outer_middleware(DatabaseMiddleware(db))
    dp.update.outer_middleware(AccessMiddleware(TelegramNotifier(bot)))
    dp.include_router(build_router())
    return dp


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


async def point_team_at(bot: Bot, db: Database, webapp: WebAppLink) -> None:
    """Re-points every team member's menu button at the Mini App's current address."""
    async with db.session() as session:
        users = [u for u in await UserService(session).list_all() if u.is_active]
    await webapp.apply(bot, users)
