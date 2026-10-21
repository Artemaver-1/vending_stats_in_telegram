import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser

from app.db import Database
from app.domain.enums import UserRole
from app.services.notifications import Messages, Notifier
from app.services.staff import UserService

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class DatabaseMiddleware(BaseMiddleware):
    """Opens a session per update and commits it once the handler returns."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self.db.session() as session:
            data["session"] = session
            return await handler(event, data)


class AccessMiddleware(BaseMiddleware):
    """Lets only active team members through and turns everyone else into an access request."""

    def __init__(self, notifier: Notifier) -> None:
        self.notifier = notifier

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user: TelegramUser | None = data.get("event_from_user")
        if tg_user is None:
            return None

        users = UserService(data["session"])
        known = await users.by_telegram_id(tg_user.id)
        user = await users.register_visitor(tg_user.id, tg_user.full_name, tg_user.username)
        if user.is_active:
            data["user"] = user
            return await handler(event, data)

        logger.info("Access request from %s (@%s)", tg_user.id, tg_user.username)
        await data["bot"].send_message(
            tg_user.id,
            "Здравствуйте! Доступа пока нет — я передал запрос администратору.\n"
            f"Ваш Telegram ID: <code>{tg_user.id}</code>",
        )
        if known is None:
            await self.notifier.send(
                await users.telegram_ids(UserRole.ADMIN),
                Messages.access_request(tg_user.full_name, tg_user.username, tg_user.id),
            )
        return None
