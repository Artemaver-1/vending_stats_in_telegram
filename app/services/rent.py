from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import Clock
from app.db.models import RentContract, RentPayment
from app.domain.enums import RentType
from app.domain.inspection import REMINDER_OFFSETS
from app.domain.periods import iter_months, month_start, next_month, previous_month
from app.services.finance import FinanceService


class RentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ContractTerms:
    location_id: int
    rent_type: RentType
    amount: Decimal
    payment_day: int
    valid_from: date
    valid_to: date | None = None

    def validate(self) -> None:
        if self.amount <= 0:
            raise RentError("Сумма или процент должны быть больше нуля")
        if self.rent_type is RentType.PERCENT and self.amount > 100:
            raise RentError("Процент не может быть больше 100")
        if not 1 <= self.payment_day <= 28:
            raise RentError("День оплаты — от 1 до 28")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise RentError("Дата окончания раньше даты начала")


@dataclass(frozen=True, slots=True)
class UpcomingRent:
    contract: RentContract
    period: date
    estimate: Decimal
    due_on: date


class RentService:
    """Keeps one RentPayment per contract and finished month.

    Unpaid percentage rent is recalculated on every sync, since late telemetry uploads can
    still change that month's revenue; once marked paid the amount is frozen.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock
        self.finance = FinanceService(session)

    async def contracts(self) -> Sequence[RentContract]:
        result = await self.session.scalars(
            select(RentContract)
            .options(selectinload(RentContract.location))
            .order_by(RentContract.valid_from.desc())
        )
        return result.all()

    async def get_contract(self, contract_id: int) -> RentContract | None:
        return await self.session.get(RentContract, contract_id)

    async def save_contract(
        self, terms: ContractTerms, contract: RentContract | None = None
    ) -> RentContract:
        terms.validate()
        contract = contract or RentContract(location_id=terms.location_id)
        contract.location_id = terms.location_id
        contract.rent_type = terms.rent_type
        contract.fixed_amount = terms.amount if terms.rent_type is RentType.FIXED else None
        contract.revenue_percent = terms.amount if terms.rent_type is RentType.PERCENT else None
        contract.payment_day = terms.payment_day
        contract.valid_from = terms.valid_from
        contract.valid_to = terms.valid_to
        self.session.add(contract)
        await self.session.flush()
        await self.sync_accruals()
        return contract

    async def delete_contract(self, contract: RentContract) -> None:
        await self.session.delete(contract)
        await self.session.flush()

    async def sync_accruals(self) -> None:
        last_closed = previous_month(month_start(self.clock.today()))
        existing = {
            (p.contract_id, p.period): p for p in await self.session.scalars(select(RentPayment))
        }
        for contract in await self.contracts():
            stop = min(last_closed, month_start(contract.valid_to or last_closed))
            for period in iter_months(contract.valid_from, stop):
                payment = existing.get((contract.id, period))
                if payment is not None and payment.is_paid:
                    continue
                amount = await self.finance.rent_charge(contract, period)
                if payment is None:
                    self.session.add(
                        RentPayment(contract_id=contract.id, period=period, amount=amount)
                    )
                else:
                    payment.amount = amount
        await self.session.flush()

    async def payments(self) -> Sequence[RentPayment]:
        result = await self.session.scalars(
            select(RentPayment)
            .options(selectinload(RentPayment.contract).selectinload(RentContract.location))
            .order_by(RentPayment.period.desc(), RentPayment.id)
        )
        return result.all()

    async def upcoming(self) -> list[UpcomingRent]:
        """Estimates for the month in progress, which isn't accrued yet."""
        period = month_start(self.clock.today())
        result = []
        for contract in await self.contracts():
            started = contract.valid_from <= self.clock.today()
            ended = contract.valid_to is not None and contract.valid_to < period
            if started and not ended:
                result.append(
                    UpcomingRent(
                        contract=contract,
                        period=period,
                        estimate=await self.finance.rent_charge(contract, period),
                        due_on=next_month(period).replace(day=contract.payment_day),
                    )
                )
        return result

    async def get_payment(self, payment_id: int) -> RentPayment | None:
        return await self.session.scalar(
            select(RentPayment)
            .where(RentPayment.id == payment_id)
            .options(selectinload(RentPayment.contract).selectinload(RentContract.location))
        )

    async def set_paid(self, payment: RentPayment, paid: bool) -> None:
        payment.paid_on = self.clock.today() if paid else None
        await self.session.flush()

    async def due_reminders(self) -> list[RentPayment]:
        today = self.clock.today()
        return [
            p
            for p in await self.payments()
            if not p.is_paid
            and (p.due_on - today).days in REMINDER_OFFSETS
            and p.reminded_on != today
        ]
