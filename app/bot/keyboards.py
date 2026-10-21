from datetime import date
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.bot.formatting import MONTHS
from app.domain.periods import next_month, previous_month


class MainMenu(StrEnum):
    FINANCE = "📊 Финансы"
    PAYBACK = "⏳ Окупаемость"


class PnlPage(CallbackData, prefix="pnl"):
    year: int
    month: int

    @classmethod
    def of(cls, period: date) -> "PnlPage":
        return cls(year=period.year, month=period.month)

    @property
    def period(self) -> date:
        return date(self.year, self.month, 1)


def main_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for item in MainMenu:
        builder.button(text=item.value)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def pnl_navigation(period: date, today: date) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    prev_ = previous_month(period)
    builder.button(text=f"◀ {MONTHS[prev_.month - 1]}", callback_data=PnlPage.of(prev_))
    next_ = next_month(period)
    if next_ <= today:
        builder.button(text=f"{MONTHS[next_.month - 1]} ▶", callback_data=PnlPage.of(next_))
    return builder.as_markup()
