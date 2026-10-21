from datetime import date, datetime
from zoneinfo import ZoneInfo


class Clock:
    """Single source of "now" in the business timezone; swapped for a fixed one in tests."""

    def __init__(self, tz: ZoneInfo) -> None:
        self.tz = tz

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()
