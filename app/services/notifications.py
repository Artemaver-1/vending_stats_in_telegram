import logging
from collections.abc import Collection
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...


class TelegramNotifier:
    def __init__(self, bot: Bot, recipients: Collection[int]) -> None:
        self.bot = bot
        self.recipients = tuple(recipients)

    async def send(self, text: str) -> None:
        for chat_id in self.recipients:
            try:
                await self.bot.send_message(chat_id, text)
            except TelegramAPIError:
                # One blocked or deleted chat shouldn't stop alerts to everyone else.
                logger.exception("Failed to notify %s", chat_id)
