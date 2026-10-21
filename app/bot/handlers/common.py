from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.webapp_link import WebAppLink, button_text
from app.db.models import User

router = Router(name="common")


def open_app_keyboard(link: WebAppLink, user: User) -> InlineKeyboardMarkup | None:
    if link.url is None:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text=f"📱 {button_text(user)}", web_app=WebAppInfo(url=link.url))
    return builder.as_markup()


@router.message(CommandStart())
@router.message(Command("app"))
async def start(message: Message, user: User, webapp: WebAppLink) -> None:
    if message.bot is not None:
        await webapp.apply(message.bot, [user])
    keyboard = open_app_keyboard(webapp, user)
    if keyboard is None:
        await message.answer("Приложение запускается, попробуйте через минуту: /app")
        return
    if user.is_admin:
        text = "Панель управления силомерами — финансы, задачи, аренда и аппараты."
    else:
        text = "Обслуживание силомеров: здесь ваши задачи и проверки."
    await message.answer(f"{text}\nОткройте приложение кнопкой ниже 👇", reply_markup=keyboard)


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    if message.from_user is not None:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message()
async def fallback(message: Message, user: User, webapp: WebAppLink) -> None:
    await message.answer(
        "Всё делается в приложении 👇", reply_markup=open_app_keyboard(webapp, user)
    )
