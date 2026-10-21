from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.db.models import ConnectionEvent, Machine
from app.domain.enums import ExpenseCategory, PaymentChannel
from app.domain.finance import MonthlyPnL, PaybackStatus

MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)  # fmt: skip

CHANNEL_LABELS = {
    PaymentChannel.CARD: "Карты",
    PaymentChannel.COIN: "Монеты",
    PaymentChannel.BILL: "Купюры",
}

EXPENSE_LABELS = {
    ExpenseCategory.PARTS: "Комплектующие",
    ExpenseCategory.REPAIR: "Ремонт",
    ExpenseCategory.ACQUIRING_FEE: "Эквайринг",
    ExpenseCategory.CONNECTIVITY: "Связь",
    ExpenseCategory.TRANSPORT: "Транспорт",
    ExpenseCategory.OTHER: "Прочее",
}


def rub(value: Decimal) -> str:
    sign = "−" if value < 0 else ""
    value = abs(value)
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{sign}{text.replace(',', ' ').replace('.', ',')} ₽"


def month_title(period: date) -> str:
    return f"{MONTHS[period.month - 1].capitalize()} {period.year}"


def render_pnl(pnl: MonthlyPnL, *, title: str | None = None) -> str:
    lines = [f"<b>{title or month_title(pnl.period)}</b>", ""]

    lines.append(f"💰 <b>Выручка: {rub(pnl.total_revenue)}</b>")
    for channel in PaymentChannel:
        if amount := pnl.revenue.get(channel):
            lines.append(f"  • {CHANNEL_LABELS[channel]}: {rub(amount)}")

    lines.append("")
    lines.append(f"📉 <b>Расходы: {rub(pnl.total_expenses)}</b>")
    if pnl.rent:
        lines.append(f"  • Аренда: {rub(pnl.rent)}")
    for category in ExpenseCategory:
        if amount := pnl.expenses.get(category):
            lines.append(f"  • {EXPENSE_LABELS[category]}: {rub(amount)}")

    lines.append("")
    marker = "✅" if pnl.net_profit >= 0 else "🔻"
    lines.append(f"{marker} <b>Чистая прибыль: {rub(pnl.net_profit)}</b>")
    return "\n".join(lines)


def render_payback(name: str, status: PaybackStatus) -> str:
    filled = round(status.progress * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    lines = [
        f"<b>{name}</b>",
        f"{bar} {status.progress:.0%}",
        f"Вложено: {rub(status.investment)}",
        f"Заработано: {rub(status.earned)}",
    ]
    if status.reached_in is not None:
        lines.append(f"🎉 Окупился: {month_title(status.reached_in).lower()}")
    else:
        lines.append(f"Осталось: {rub(status.remaining)}")
    return "\n".join(lines)


def uptime_cell(share: float | None) -> str:
    if share is None:
        return "⬜"
    if share >= 0.95:
        return "🟩"
    if share >= 0.5:
        return "🟨"
    if share > 0:
        return "🟧"
    return "🟥"


def render_uptime_grid(uptime: dict[date, float | None]) -> str:
    """Calendar of the given days, one row per week starting on Monday."""
    days = sorted(uptime)
    if not days:
        return ""
    cells = ["  "] * days[0].weekday() + [uptime_cell(uptime[d]) for d in days]
    rows = [" ".join(cells[i : i + 7]) for i in range(0, len(cells), 7)]
    return "\n".join(rows)


def render_machine_status(machine: Machine, uptime: dict[date, float | None], tz: ZoneInfo) -> str:
    if machine.is_online is None:
        status = "⚪ статус неизвестен"
    elif machine.is_online:
        status = "🟢 на связи"
    else:
        status = "🔴 нет связи"
    if machine.status_checked_at is not None:
        status += f" (проверено {machine.status_checked_at.astimezone(tz):%d.%m %H:%M})"

    known = [share for share in uptime.values() if share is not None]
    average = f"{sum(known) / len(known):.0%}" if known else "—"
    first, last = min(uptime), max(uptime)
    return (
        f"<b>{machine.name}</b>\n{status}\n"
        f"Онлайн {first:%d.%m}–{last:%d.%m}: {average}\n"
        f"<code>{render_uptime_grid(uptime)}</code>"
    )


def render_connection_event(event: ConnectionEvent, tz: ZoneInfo) -> str:
    at = event.occurred_at.astimezone(tz)
    if event.online:
        return f"🟢 <b>{event.machine.name}</b>: связь восстановлена в {at:%H:%M %d.%m}"
    return f"🔴 <b>{event.machine.name}</b>: связь потеряна в {at:%H:%M %d.%m}"


UPTIME_LEGEND = "🟩 ≥95%  🟨 ≥50%  🟧 <50%  🟥 офлайн  ⬜ нет данных"
