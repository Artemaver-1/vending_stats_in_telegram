import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import Machine, User
from app.domain.enums import PaymentChannel
from app.formatting import CHANNEL_DEVICES, human_date, plural
from app.services.downtime import DowntimeService
from app.services.payment_watch import PaymentWatch
from app.services.tasks import TaskService

# The widget has room for a word, not for the bank's name.
SHORT_DEVICES = {**CHANNEL_DEVICES, PaymentChannel.CARD: "терминал"}


class WidgetService:
    """Feeds the iPhone home-screen widget of the service team."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def token_for(self, user: User) -> str:
        if user.widget_token is None:
            user.widget_token = secrets.token_urlsafe(24)
            await self.session.flush()
        return user.widget_token

    async def user_by_token(self, token: str) -> User | None:
        user = await self.session.scalar(select(User).where(User.widget_token == token))
        return user if user is not None and user.is_active else None

    async def snapshot(self) -> dict[str, Any]:
        today = self.clock.today()
        # "alerts" is what widgets installed before the redesign read; the newer script
        # draws from "down" and "checks".
        alerts: list[dict[str, str]] = []
        down: list[dict[str, Any]] = []
        for item in await DowntimeService(self.session, self.clock).all_down():
            why = "сломан" if item.broken else "нет связи"
            word = plural(item.days, "день", "дня", "дней")
            text = f"«{item.machine.name}» стоит {item.days} {word} ({why})"
            alerts.append({"level": "down", "text": text})
            down.append(
                {"machine": item.machine.name, "reason": why, "days": item.days, "days_word": word}
            )

        # A machine that stands idle takes no payments at all, so its acceptors can wait.
        idle = {item["machine"] for item in down}
        checks: dict[str, list[str]] = {}
        for alert in await PaymentWatch(self.session, self.clock).open_alerts():
            name = alert.machine.name
            if name in idle:
                continue
            device = CHANNEL_DEVICES[alert.channel]
            alerts.append({"level": "payment", "text": f"«{name}»: проверьте {device}"})
            checks.setdefault(name, []).append(SHORT_DEVICES[alert.channel])
        machines = await self.session.scalars(
            select(Machine.name).where(Machine.is_active).order_by(Machine.name)
        )

        tasks = list(await TaskService(self.session, self.clock).team_open())
        upcoming = [t for t in tasks if t.due_on is not None]
        upcoming.sort(key=lambda t: t.due_on or today)
        undated = [t for t in tasks if t.due_on is None]
        next_task = None
        if upcoming:
            task = upcoming[0]
            assert task.due_on is not None
            next_task = {
                "title": task.title,
                "when": human_date(task.due_on, today),
                "overdue": task.due_on < today,
            }
        return {
            "updated": datetime.now(self.clock.tz).strftime("%H:%M"),
            "alerts": alerts,
            "down": down,
            "checks": [{"machine": name, "devices": devices} for name, devices in checks.items()],
            "machines": list(machines),
            "next_task": next_task,
            "open_tasks": len(tasks),
            "undated_tasks": [t.title for t in undated],
        }
