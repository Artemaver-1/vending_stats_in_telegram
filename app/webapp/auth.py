import hashlib
import hmac
import time
from datetime import timedelta
from typing import Annotated

from aiogram.utils.web_app import WebAppInitData, safe_parse_webapp_init_data
from fastapi import Depends, HTTPException, Request, status

from app.api.deps import SessionDep
from app.config import Settings
from app.db.models import User
from app.services.staff import UserService

# Telegram signs init data once when the Mini App opens; a day is plenty for one session.
INIT_DATA_TTL = timedelta(hours=24)
LINK_TTL = timedelta(hours=12)


class InitDataError(ValueError):
    pass


def parse_init_data(init_data: str, bot_token: str, *, now: float | None = None) -> WebAppInitData:
    try:
        data = safe_parse_webapp_init_data(bot_token, init_data)
    except ValueError as exc:
        raise InitDataError("bad signature") from exc
    age = (now or time.time()) - data.auth_date.timestamp()
    if age > INIT_DATA_TTL.total_seconds():
        raise InitDataError("init data expired")
    if data.user is None:
        raise InitDataError("no user in init data")
    return data


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def current_user(
    request: Request,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> User:
    scheme, _, init_data = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "tma" or not init_data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Откройте приложение из Telegram")
    try:
        data = parse_init_data(init_data, settings.bot_token.get_secret_value())
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия устарела") from exc

    assert data.user is not None
    user = await UserService(session).by_telegram_id(data.user.id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа")
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только для администратора")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(admin_user)]


class LinkSigner:
    """Signs URLs for resources the browser loads by itself (images), where no
    Authorization header can be attached."""

    def __init__(self, secret: str) -> None:
        self._key = hashlib.sha256(f"links:{secret}".encode()).digest()

    def sign(self, path: str, *, now: float | None = None) -> str:
        expires = int((now or time.time()) + LINK_TTL.total_seconds())
        return f"{path}?exp={expires}&sig={self._digest(path, expires)}"

    def verify(self, path: str, expires: int, signature: str, *, now: float | None = None) -> bool:
        if expires < (now or time.time()):
            return False
        return hmac.compare_digest(self._digest(path, expires), signature)

    def _digest(self, path: str, expires: int) -> str:
        return hmac.new(self._key, f"{path}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]
