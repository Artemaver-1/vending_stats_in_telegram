import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    logger.exception("Update %s failed", event.update.update_id, exc_info=event.exception)

    text = "⚠️ Что-то пошло не так, данные не сохранены. Попробуйте ещё раз."
    if event.update.message is not None:
        await event.update.message.answer(text)
    elif event.update.callback_query is not None:
        await event.update.callback_query.answer(text, show_alert=True)
    return True
