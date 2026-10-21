from aiogram import Router

from app.bot.handlers import common, errors


def build_router() -> Router:
    root = Router(name="root")
    root.include_routers(errors.router, common.router)
    return root
