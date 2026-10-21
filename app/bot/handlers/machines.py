from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import UPTIME_LEGEND, render_machine_status
from app.bot.keyboards import MainMenu
from app.clock import Clock
from app.repositories import MachineRepository
from app.services.uptime import UptimeService

router = Router(name="machines")

HISTORY_DAYS = 28


@router.message(Command("machines"))
@router.message(F.text == MainMenu.MACHINES)
async def machines_status(message: Message, session: AsyncSession, clock: Clock) -> None:
    machines = await MachineRepository(session).list_active()
    if not machines:
        await message.answer(
            "Аппаратов пока нет — они появятся после первой синхронизации SmartVend."
        )
        return

    today = clock.today()
    first = today - timedelta(days=HISTORY_DAYS - 1)
    uptime = UptimeService(session, clock)
    blocks = [
        render_machine_status(machine, await uptime.daily(machine, first, today), clock.tz)
        for machine in machines
    ]
    await message.answer("\n\n".join([*blocks, UPTIME_LEGEND]))
