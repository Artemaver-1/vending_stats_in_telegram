from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import render_payback, render_pnl
from app.bot.keyboards import MainMenu, PnlPage, pnl_navigation
from app.clock import Clock
from app.domain.periods import month_start
from app.services.finance import FinanceService

router = Router(name="finance")


@router.message(Command("month"))
@router.message(F.text == MainMenu.FINANCE)
async def current_month(message: Message, session: AsyncSession, clock: Clock) -> None:
    today = clock.today()
    pnl = await FinanceService(session).monthly_pnl(today)
    await message.answer(render_pnl(pnl), reply_markup=pnl_navigation(pnl.period, today))


@router.callback_query(PnlPage.filter())
async def switch_month(
    callback: CallbackQuery, callback_data: PnlPage, session: AsyncSession, clock: Clock
) -> None:
    today = clock.today()
    period = min(callback_data.period, month_start(today))
    pnl = await FinanceService(session).monthly_pnl(period)

    if callback.message is not None and not isinstance(callback.message, InaccessibleMessage):
        await callback.message.edit_text(
            render_pnl(pnl), reply_markup=pnl_navigation(period, today)
        )
    await callback.answer()


@router.message(Command("payback"))
@router.message(F.text == MainMenu.PAYBACK)
async def payback(message: Message, session: AsyncSession, clock: Clock) -> None:
    service = FinanceService(session)
    today = clock.today()

    blocks = [render_payback("Весь бизнес", await service.business_payback(today))]
    for machine in await service.machines.list_active():
        status = await service.machine_payback(machine.id, today)
        blocks.append(render_payback(machine.name, status))

    await message.answer("\n\n".join(blocks))
