import logging
from collections.abc import Iterable

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.db.models import User

logger = logging.getLogger(__name__)


def button_text(user: User) -> str:
    return "Панель" if user.is_admin else "Обслуживание"


class WebAppLink:
    """Knows the current public address of the Mini App.

    A fixed WEBAPP_URL wins. Otherwise the address of the Cloudflare quick tunnel is read
    from its metrics server; it changes whenever the tunnel restarts, so callers poll
    `refresh()` and re-point menu buttons when it returns True.
    """

    def __init__(self, fixed_url: str | None, tunnel_metrics_url: str) -> None:
        self.url: str | None = _app_url(fixed_url) if fixed_url else None
        self._fixed = fixed_url is not None
        self._metrics_url = tunnel_metrics_url.rstrip("/") + "/quicktunnel"

    async def refresh(self) -> bool:
        if self._fixed:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(self._metrics_url)
                hostname = response.json().get("hostname")
        except (httpx.HTTPError, ValueError):
            logger.warning("Tunnel address is not available yet")
            return False
        if not hostname:
            return False
        url = _app_url(f"https://{hostname}")
        changed = url != self.url
        self.url = url
        return changed

    async def apply(self, bot: Bot, users: Iterable[User]) -> None:
        """Points the chat menu button of every team member at the current address."""
        if self.url is None:
            return
        for user in users:
            try:
                await bot.set_chat_menu_button(
                    chat_id=user.telegram_id,
                    menu_button=MenuButtonWebApp(
                        text=button_text(user), web_app=WebAppInfo(url=self.url)
                    ),
                )
            except TelegramAPIError:
                logger.exception("Failed to set menu button for %s", user.telegram_id)


def _app_url(base: str) -> str:
    return base.rstrip("/") + "/app"
