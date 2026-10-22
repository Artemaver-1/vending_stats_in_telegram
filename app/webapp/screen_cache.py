"""Keeps the heavy start screens for a few minutes.

The database is far away, so a screen built from scratch takes a second or two. Any
change made in the app, by a timer or by Telegram arrives as a POST and empties the
cache, so a person never sees their own edit missing; data that changes by itself
(new sales) shows up within `TTL`. Each cloud instance has its own cache.
"""

import re
import time
from dataclasses import dataclass
from datetime import date

from fastapi import Request, Response

from app.webapp.auth import InitDataError, init_data_of, parse_init_data

TTL = 180
CACHED = re.compile(r"^/app/(home|admin|service|admin/ofr|admin/finance|machines/\d+)$")


@dataclass(frozen=True, slots=True)
class _Entry:
    stored_at: float
    body: bytes
    headers: dict[str, str]


class ScreenCache:
    def __init__(self, bot_token: str, ttl: float = TTL) -> None:
        self.bot_token = bot_token
        self.ttl = ttl
        self._entries: dict[tuple[str, int, date], _Entry] = {}

    def key(self, request: Request, today: date) -> tuple[str, int, date] | None:
        """Only signed-in htmx requests for the listed screens are cached, per person and
        per day: screens show things like "today" and the once-a-day loading video."""
        if request.method != "GET" or "HX-Request" not in request.headers:
            return None
        if not CACHED.match(request.url.path):
            return None
        try:
            data = parse_init_data(init_data_of(request), self.bot_token)
        except InitDataError:
            return None
        assert data.user is not None
        return str(request.url.path) + "?" + str(request.url.query), data.user.id, today

    def get(self, key: tuple[str, int, date]) -> Response | None:
        entry = self._entries.get(key)
        if entry is None or time.monotonic() - entry.stored_at > self.ttl:
            return None
        return Response(entry.body, headers=entry.headers)

    def put(self, key: tuple[str, int, date], body: bytes, headers: dict[str, str]) -> None:
        self._entries[key] = _Entry(time.monotonic(), body, headers)

    def clear(self) -> None:
        self._entries.clear()
