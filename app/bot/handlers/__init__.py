from aiogram import Router

from app.bot.handlers import common, errors, finance, machines


def build_router() -> Router:
    root = Router(name="root")
    root.include_routers(errors.router, common.router, finance.router, machines.router)
    return root
