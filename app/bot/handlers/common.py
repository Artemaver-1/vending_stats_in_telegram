from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.webapp_link import WebAppLink
from app.db.models import User

router = Router(name="common")

WELCOME_PICTURE = Path(__file__).parents[2] / "webapp" / "static" / "welcome.jpg"

ADMIN_WELCOME = (
    "<b>силомеры.рф</b> — панель управления\n\n"
    "Задачи, статистика, оплата аренды и прибыль — всё в приложении 👇"
)
SERVICE_WELCOME = "<b>Обслуживание силомеров</b>\n\nВаши задачи и отчёты — в приложении 👇"


class WelcomePicture:
    """Sends the picture once and reuses Telegram's file_id afterwards. While the Mini App
    has a public address, Telegram fetches the picture from there instead of an upload."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.file_id: str | None = None

    def input(self, link: WebAppLink) -> str | FSInputFile:
        if self.file_id:
            return self.file_id
        if link.url:
            return link.url.removesuffix("/app") + "/static/" + self.path.name
        return FSInputFile(self.path)

    def remember(self, message: Message) -> None:
        if message.photo:
            self.file_id = message.photo[-1].file_id


welcome_picture = WelcomePicture(WELCOME_PICTURE)


def open_app_keyboard(link: WebAppLink, user: User) -> InlineKeyboardMarkup | None:
    if link.url is None:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Открыть приложение", web_app=WebAppInfo(url=link.url))
    return builder.as_markup()


@router.message(CommandStart())
async def start(message: Message, user: User, webapp: WebAppLink) -> None:
    if message.bot is not None:
        await webapp.apply(message.bot, [user])
    keyboard = open_app_keyboard(webapp, user)
    if keyboard is None:
        await message.answer("Приложение запускается, отправьте /start через минуту.")
        return

    if user.is_admin:
        sent = await message.answer_photo(
            welcome_picture.input(webapp), caption=ADMIN_WELCOME, reply_markup=keyboard
        )
        welcome_picture.remember(sent)
    else:
        await message.answer(SERVICE_WELCOME, reply_markup=keyboard)


@router.message()
async def everything_else(message: Message, user: User, webapp: WebAppLink) -> None:
    # The chat itself has no features: anything typed just points back to the Mini App.
    await message.answer(
        "Всё делается в приложении 👇", reply_markup=open_app_keyboard(webapp, user)
    )
