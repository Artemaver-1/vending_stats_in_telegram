import logging
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from typing import Protocol
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from app.db.models import ConnectionEvent, RentPayment, Task
from app.formatting import human_date, month_title, rub
from app.services.tasks import InspectionOutcome

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Photo:
    filename: str
    data: bytes


class Notifier(Protocol):
    async def send(
        self, chat_ids: Iterable[int], text: str, *, photo: Photo | None = None
    ) -> None: ...


class TelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_ids: Iterable[int], text: str, *, photo: Photo | None = None) -> None:
        for chat_id in chat_ids:
            try:
                if photo is None:
                    await self.bot.send_message(chat_id, text)
                else:
                    file = BufferedInputFile(photo.data, filename=photo.filename)
                    await self.bot.send_photo(chat_id, file, caption=text)
            except TelegramAPIError:
                # One blocked or deleted chat shouldn't stop alerts to everyone else.
                logger.exception("Failed to notify %s", chat_id)


class Messages:
    """Texts of everything the bot sends on its own; HTML parse mode."""

    @staticmethod
    def connection(event: ConnectionEvent, tz: ZoneInfo) -> str:
        at = event.occurred_at.astimezone(tz)
        name = escape(event.machine.name)
        if event.online:
            return f"🟢 <b>{name}</b>: связь восстановлена в {at:%H:%M %d.%m}"
        return f"🔴 <b>{name}</b>: связь потеряна в {at:%H:%M %d.%m}"

    @staticmethod
    def inspection_report(outcome: InspectionOutcome, author: str) -> str:
        task = outcome.task
        machine = escape(task.machine.name) if task.machine else "без аппарата"
        if outcome.machine_broke:
            head = f"🚨 <b>Отчёт «{machine}»: силомер не работает</b>"
        elif outcome.machine_fixed:
            head = f"🛠 <b>Отчёт «{machine}»: снова работает</b>"
        elif outcome.failed:
            head = f"⚠️ <b>Отчёт «{machine}»: есть неполадки</b>"
        else:
            head = f"✅ <b>Отчёт «{machine}»: всё работает</b>"

        lines = [head, f"От: {escape(author)}"]
        lines += [f"{'✅' if c.ok else '❌'} {escape(c.label)}" for c in task.checks]
        if task.comment:
            lines.append(f"💬 {escape(task.comment)}")
        if outcome.machine_broke:
            lines.append("Еженедельные проверки по аппарату на паузе до ремонта.")
        return "\n".join(lines)

    @staticmethod
    def new_task(task: Task) -> str:
        lines = [f"📌 <b>Новая задача</b>: {escape(task.title)}"]
        if task.machine:
            lines.append(f"Силомер: {escape(task.machine.name)}")
        lines.append(f"Когда: {human_date(task.due_on)}")
        if task.description:
            lines.append(escape(task.description))
        return "\n".join(lines)

    @staticmethod
    def task_done(task: Task) -> str:
        who = escape(task.completed_by.name) if task.completed_by else "—"
        lines = [f"✅ <b>Выполнено</b>: {escape(task.title)}", f"Кто: {who}"]
        if task.comment:
            lines.append(f"💬 {escape(task.comment)}")
        return "\n".join(lines)

    @staticmethod
    def task_reminder(task: Task, days_left: int) -> str:
        when = "завтра" if days_left == 1 else f"через {days_left} дня"
        return f"⏰ Напоминание: {when} — {escape(task.title)}"

    @staticmethod
    def rent_reminder(payment: RentPayment) -> str:
        location = escape(payment.contract.location.name)
        return (
            f"💳 <b>Аренда «{location}»</b> за {month_title(payment.period).lower()}: "
            f"{rub(payment.amount)}\nОплатить до {human_date(payment.due_on)}"
        )

    @staticmethod
    def access_request(name: str, username: str | None, telegram_id: int) -> str:
        handle = f" (@{escape(username)})" if username else ""
        return (
            f"👤 {escape(name)}{handle} открыл бота, ID <code>{telegram_id}</code>.\n"
            "Открыть доступ можно в разделе «Команда»."
        )
