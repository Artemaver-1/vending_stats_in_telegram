import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.clock import Clock

TZ = ZoneInfo("Asia/Yekaterinburg")
BOT_TOKEN = "123456:TEST-token"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        super().__init__(TZ)
        self._now = now

    def now(self) -> datetime:
        return self._now

    def shift(self, **delta: float) -> None:
        self._now += timedelta(**delta)


def make_init_data(
    user_id: int, name: str = "Тест", *, token: str = BOT_TOKEN, auth_date: int | None = None
) -> str:
    """Builds init data signed the way Telegram signs it for a Mini App."""
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": name}, ensure_ascii=False),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[list[int], str, bool]] = []

    async def send(self, chat_ids: object, text: str, *, photo: object = None) -> None:
        self.sent.append((list(chat_ids), text, photo is not None))  # type: ignore[call-overload]
