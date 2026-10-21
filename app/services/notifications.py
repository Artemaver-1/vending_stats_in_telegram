import logging
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from typing import Protocol
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from app.db.models import ConnectionEvent, Encashment, PaymentAlert, RentPayment, Task
from app.formatting import CHANNEL_DEVICES, human_date, month_title, plural, rub
from app.services.downtime import Downtime
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

    async def send_document(
        self, chat_id: int, filename: str, data: bytes, caption: str
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

    async def send_document(self, chat_id: int, filename: str, data: bytes, caption: str) -> None:
        file = BufferedInputFile(data, filename=filename)
        await self.bot.send_document(chat_id, file, caption=caption)


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
    def inspection_report(
        outcome: InspectionOutcome, author: str, encashment: Encashment | None = None
    ) -> str:
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
        if encashment is not None:
            took = [
                w
                for w, t in (("купюры", encashment.took_bills), ("монеты", encashment.took_coins))
                if t
            ]
            line = "💵 Забрал " + " и ".join(took)
            if encashment.expected is not None:
                line += f" — по SmartVend там ≈ {rub(encashment.expected)}"
            lines.append(line)
        if outcome.machine_broke:
            lines.append("Еженедельные проверки по аппарату на паузе до ремонта.")
        return "\n".join(lines)

    @staticmethod
    def new_task(task: Task) -> str:
        lines = [f"📌 <b>Новая задача</b>: {escape(task.title)}"]
        if task.machine:
            lines.append(f"Силомер: {escape(task.machine.name)}")
        if task.due_on is not None:
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

    @staticmethod
    def cash_counted(encashment: Encashment, author: str) -> str:
        lines = [
            f"🧮 <b>Посчитаны деньги «{escape(encashment.machine.name)}»</b>",
            f"Кто: {escape(author)}",
        ]
        if encashment.bills is not None:
            lines.append(f"Купюры: {rub(encashment.bills)}")
        if encashment.coins is not None:
            lines.append(f"Монеты: {rub(encashment.coins)}")
        counted, expected = encashment.counted, encashment.expected
        if counted is not None and expected is not None:
            diff = counted - expected
            verdict = "сходится" if diff == 0 else f"разница {'+' if diff > 0 else ''}{rub(diff)}"
            lines.append(f"По SmartVend ожидалось {rub(expected)} — {verdict}")
        return "\n".join(lines)

    @staticmethod
    def cash_deposited(encashment: Encashment, author: str) -> str:
        deposited = encashment.deposited or 0
        machine = escape(encashment.machine.name)
        lines = [
            f"🏦 <b>Внесено в банк {rub(deposited)}</b> — «{machine}»",
            f"Кто: {escape(author)}",
        ]
        counted = encashment.counted
        if counted is not None and counted != deposited:
            lines.append(f"Посчитано было {rub(counted)}, разница {rub(counted - deposited)}")
        return "\n".join(lines)

    @staticmethod
    def downtime(downtime: Downtime) -> str:
        name = escape(downtime.machine.name)
        days = f"{downtime.days} {plural(downtime.days, 'день', 'дня', 'дней')}"
        why = "сломан" if downtime.broken else "нет связи"
        lines = [
            f"🚨🚨🚨 <b>«{name}» стоит уже {days}!</b> ({why})",
            "Силомер не работает — чините как можно скорее! 🔧",
            "Когда заработает — заполните отчёт по силомеру.",
        ]
        return "\n".join(lines)

    @staticmethod
    def from_admin(author: str, text: str) -> str:
        return f"✉️ <b>Сообщение от {escape(author)}</b>\n\n{escape(text.strip())}"

    @staticmethod
    def payment_alert(alert: PaymentAlert) -> str:
        device = CHANNEL_DEVICES[alert.channel]
        name = escape(alert.machine.name)
        return (
            f"⚠️ <b>«{name}»: проверьте {device}!</b>\n"
            f"Силомер продаёт ({alert.recent_sales} оплат за 2 дня), а этим способом "
            "за это время почти никто не заплатил. Возможно, он плохо работает или сломан."
        )

    @staticmethod
    def payment_alert_cleared(alert: PaymentAlert) -> str:
        device = CHANNEL_DEVICES[alert.channel]
        return f"✅ «{escape(alert.machine.name)}»: {device} снова принимает оплату."
