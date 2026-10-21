import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.db import Database

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AccessMiddleware(BaseMiddleware):
    """Drops every update from users who aren't on the allow list."""

    def __init__(self, allowed_ids: Collection[int]) -> None:
        self.allowed_ids = frozenset(allowed_ids)

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and user.id in self.allowed_ids:
            return await handler(event, data)

        if user is not None:
            logger.warning("Rejected update from %s (@%s)", user.id, user.username)
            bot = data["bot"]
            await bot.send_message(
                user.id,
                f"Доступ закрыт. Ваш Telegram ID: <code>{user.id}</code>\n"
                "Передайте его владельцу бота, чтобы вас добавили.",
            )
        return None


class DatabaseMiddleware(BaseMiddleware):
    """Opens a session per update and commits it once the handler returns."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self.db.session() as session:
            data["session"] = session
            return await handler(event, data)
