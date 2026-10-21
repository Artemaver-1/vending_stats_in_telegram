from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot.keyboards import main_menu

router = Router(name="common")

HELP_TEXT = (
    "Что умеет бот:\n"
    "📊 /month — выручка, расходы и чистая прибыль за месяц\n"
    "⏳ /payback — окупаемость аппаратов\n"
    "📡 /machines — связь с аппаратами за 4 недели\n"
    "🆔 /id — показать ваш Telegram ID"
)


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(f"Привет! {HELP_TEXT}", reply_markup=main_menu())


@router.message(Command("help"))
async def help_(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    if message.from_user is not None:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")
