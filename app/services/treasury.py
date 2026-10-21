from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.clock import Clock
from app.db.models import DailyRevenue, Encashment, Expense, Ledger, Machine, Payout
from app.domain.enums import EncashmentStatus, PaidFrom, PaymentChannel
from app.domain.periods import iter_months, month_start, next_month, previous_month
from app.services.cash import EncashmentService

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class MachineCash:
    machine: Machine
    bills: Decimal | None
    coins: Decimal | None

    @property
    def total(self) -> Decimal | None:
        if self.bills is None or self.coins is None:
            return None
        return self.bills + self.coins


@dataclass(slots=True)
class Balances:
    ledger: Ledger | None
    in_machines: list[MachineCash] = field(default_factory=list)
    uncounted: list[Encashment] = field(default_factory=list)
    counted: list[Encashment] = field(default_factory=list)
    bank: Decimal | None = None
    paid_out: Decimal = ZERO

    @property
    def in_machines_total(self) -> Decimal | None:
        totals = [m.total for m in self.in_machines]
        if not totals or None in totals:
            return None
        return sum((t for t in totals if t is not None), ZERO)

    @property
    def uncounted_expected(self) -> Decimal:
        return sum((e.expected or ZERO for e in self.uncounted), ZERO)

    @property
    def counted_total(self) -> Decimal:
        return sum((e.counted or ZERO for e in self.counted), ZERO)


@dataclass(frozen=True, slots=True)
class MonthFlow:
    month: date
    card_in: Decimal
    deposited: Decimal
    spent_from_bank: Decimal
    paid_out: Decimal

    @property
    def bank_change(self) -> Decimal:
        return self.card_in + self.deposited - self.spent_from_bank - self.paid_out


class TreasuryService:
    """Where the business's money is right now.

    Cash in a machine is what SmartVend counted since the last collection. The bank
    balance is an estimate: the opening balance plus card takings and cash deposits,
    minus payouts and expenses paid from the account since money tracking began. The
    bank's own acquiring fees are not known here, so the real balance is a bit lower.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock
        self.cash = EncashmentService(session, clock)

    async def ledger(self) -> Ledger | None:
        return await self.session.get(Ledger, 1)

    async def open_ledger(self, opened_on: date, bank_opening: Decimal) -> Ledger:
        ledger = await self.ledger() or Ledger(id=1, opened_on=opened_on, bank_opening=ZERO)
        ledger.opened_on, ledger.bank_opening = opened_on, bank_opening
        self.session.add(ledger)
        await self.session.flush()
        return ledger

    async def balances(self) -> Balances:
        ledger = await self.ledger()
        result = Balances(ledger=ledger)
        for machine in await self.session.scalars(
            select(Machine).where(Machine.is_active).order_by(Machine.name)
        ):
            result.in_machines.append(
                MachineCash(
                    machine,
                    await self.cash.cash_in_machine(machine, PaymentChannel.BILL),
                    await self.cash.cash_in_machine(machine, PaymentChannel.COIN),
                )
            )
        for encashment in await self.cash.recent(limit=200):
            if encashment.status is EncashmentStatus.COLLECTED:
                result.uncounted.append(encashment)
            elif encashment.status is EncashmentStatus.COUNTED:
                result.counted.append(encashment)

        result.paid_out = await self._sum(Payout.amount)
        if ledger is not None:
            since = ledger.opened_on
            result.bank = (
                ledger.bank_opening
                + await self._card_in(since)
                + await self._sum(Encashment.deposited, Encashment.deposited_on >= since)
                - await self._sum(Payout.amount, Payout.paid_on >= since)
                - await self._sum(
                    Expense.amount, Expense.paid_from == PaidFrom.BANK, Expense.spent_on >= since
                )
            )
        return result

    async def months(self, count: int = 12) -> list[MonthFlow]:
        last = month_start(self.clock.today())
        first = last
        for _month in range(count - 1):
            first = previous_month(first)
        flows = []
        for month in iter_months(first, last):
            end = next_month(month)
            flows.append(
                MonthFlow(
                    month=month,
                    card_in=await self._card_in(month, end),
                    deposited=await self._sum(
                        Encashment.deposited,
                        Encashment.deposited_on >= month,
                        Encashment.deposited_on < end,
                    ),
                    spent_from_bank=await self._sum(
                        Expense.amount,
                        Expense.paid_from == PaidFrom.BANK,
                        Expense.spent_on >= month,
                        Expense.spent_on < end,
                    ),
                    paid_out=await self._sum(
                        Payout.amount, Payout.paid_on >= month, Payout.paid_on < end
                    ),
                )
            )
        return flows

    async def payouts(self) -> Sequence[Payout]:
        result = await self.session.scalars(
            select(Payout).order_by(Payout.paid_on.desc(), Payout.id.desc())
        )
        return result.all()

    async def paid_by_recipient(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for payout in await self.payouts():
            totals[payout.recipient] += payout.amount
        return dict(sorted(totals.items(), key=lambda kv: -kv[1]))

    async def add_payout(
        self, paid_on: date, amount: Decimal, recipient: str, note: str | None
    ) -> Payout:
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        if not recipient.strip():
            raise ValueError("Укажите, кому выплачено")
        payout = Payout(
            paid_on=paid_on,
            amount=amount,
            recipient=recipient.strip(),
            note=(note or "").strip() or None,
        )
        self.session.add(payout)
        await self.session.flush()
        return payout

    async def _card_in(self, since: date, until: date | None = None) -> Decimal:
        conditions = [DailyRevenue.channel == PaymentChannel.CARD, DailyRevenue.day >= since]
        if until is not None:
            conditions.append(DailyRevenue.day < until)
        return await self._sum(DailyRevenue.amount, *conditions)

    async def _sum(
        self, column: InstrumentedAttribute[Any], *conditions: ColumnElement[bool]
    ) -> Decimal:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(column), 0)).where(*conditions)
        )
        return Decimal(total or 0)
