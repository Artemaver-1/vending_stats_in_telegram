from datetime import date
from decimal import Decimal

from app.domain.enums import ExpenseCategory, PaidFrom, PaymentChannel
from app.domain.reconciliation import DiscrepancyKind

MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)  # fmt: skip
MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip
MONTHS_SHORT = (
    "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек",
)  # fmt: skip
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

CHANNEL_LABELS = {
    PaymentChannel.COIN: "Монеты",
    PaymentChannel.BILL: "Купюры",
    PaymentChannel.CARD: "Безнал",
}

EXPENSE_LABELS = {
    ExpenseCategory.RENT: "Аренда",
    ExpenseCategory.PARTS: "Комплектующие",
    ExpenseCategory.REPAIR: "Ремонт",
    ExpenseCategory.CONNECTIVITY: "Плата за симкарты",
    ExpenseCategory.SMARTVEND: "Плата за SmartVend",
    ExpenseCategory.STAFF: "Работник",
    ExpenseCategory.OTHER: "Прочее",
    ExpenseCategory.TAXES: "Налоги",
    ExpenseCategory.INSURANCE: "Страховые взносы",
}

PAID_FROM_LABELS = {
    PaidFrom.BANK: "со счёта ИП",
    PaidFrom.CASH: "наличными из инкассации",
    PaidFrom.PERSONAL: "из своих денег",
}

DISCREPANCY_LABELS = {
    DiscrepancyKind.SHIFTED: ("↔️", "SmartVend записал оплаты в другие дни"),
    DiscrepancyKind.SMARTVEND_DOWN: ("📵", "SmartVend не видел оплат — работала только Вендиста"),
    DiscrepancyKind.SMARTVEND_PARTIAL: ("⚠️", "SmartVend потерял часть оплат"),
    DiscrepancyKind.SMARTVEND_EXTRA: ("❓", "В SmartVend больше, чем пришло в банк"),
}


def rub(value: Decimal | int) -> str:
    value = Decimal(value)
    sign = "−" if value < 0 else ""
    value = abs(value)
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{sign}{text.replace(',', ' ').replace('.', ',')} ₽"


def month_title(period: date) -> str:
    return f"{MONTHS[period.month - 1].capitalize()} {period.year}"


def human_date(day: date, today: date | None = None) -> str:
    if today is not None:
        delta = (day - today).days
        if delta == 0:
            return "сегодня"
        if delta == 1:
            return "завтра"
        if delta == -1:
            return "вчера"
    text = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    if today is not None and day.year != today.year:
        text += f" {day.year}"
    return text


def uptime_level(share: float | None) -> str:
    if share is None:
        return "none"
    if share >= 0.95:
        return "full"
    if share >= 0.5:
        return "most"
    if share > 0:
        return "some"
    return "off"
