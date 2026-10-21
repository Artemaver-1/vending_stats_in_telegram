from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import Clock
from app.db.models import Encashment, Ledger, Machine, Task, TelemetrySale, User
from app.domain.enums import EncashmentStatus, PaymentChannel, TaskKind, TaskStatus

BANK = "Челябинвестбанк"


class CashError(ValueError):
    pass


ENCASHMENT_DETAILS = (
    selectinload(Encashment.machine),
    selectinload(Encashment.collected_by),
    selectinload(Encashment.counted_by),
    selectinload(Encashment.deposited_by),
)


class EncashmentService:
    """Follows cash from a machine to the bank account.

    Collecting creates an open-ended task to count the money; entering the counted sums
    creates a task to deposit it at the bank; confirming the deposit closes the chain.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def get(self, encashment_id: int) -> Encashment | None:
        return await self.session.scalar(
            select(Encashment).where(Encashment.id == encashment_id).options(*ENCASHMENT_DETAILS)
        )

    async def for_report(self, report_id: int) -> Encashment | None:
        return await self.session.scalar(
            select(Encashment).where(Encashment.report_id == report_id).options(*ENCASHMENT_DETAILS)
        )

    async def recent(self, limit: int = 30) -> Sequence[Encashment]:
        result = await self.session.scalars(
            select(Encashment)
            .options(*ENCASHMENT_DETAILS)
            .order_by(Encashment.collected_at.desc())
            .limit(limit)
        )
        return result.all()

    async def collect(
        self, machine: Machine, user: User, report: Task, *, bills: bool, coins: bool
    ) -> Encashment | None:
        if not (bills or coins):
            return None
        collected_at = report.completed_at or self.clock.now()
        encashment = Encashment(
            machine_id=machine.id,
            report_id=report.id,
            took_bills=bills,
            took_coins=coins,
            collected_at=collected_at,
            collected_by_id=user.id,
            expected_bills=(
                await self.cash_in_machine(machine, PaymentChannel.BILL, collected_at)
                if bills
                else None
            ),
            expected_coins=(
                await self.cash_in_machine(machine, PaymentChannel.COIN, collected_at)
                if coins
                else None
            ),
        )
        self.session.add(encashment)
        await self.session.flush()

        what = " и ".join(w for w, took in (("купюры", bills), ("монеты", coins)) if took)
        self.session.add(
            Task(
                kind=TaskKind.COUNT_CASH,
                title=f"Посчитать деньги «{machine.name}»",
                description=f"Забраны {what} {collected_at.astimezone(self.clock.tz):%d.%m}. "
                "Посчитайте на счётной машинке и впишите суммы.",
                due_on=None,
                machine_id=machine.id,
                encashment_id=encashment.id,
            )
        )
        await self.session.flush()
        return encashment

    async def count(
        self,
        encashment: Encashment,
        user: User,
        *,
        bills: Decimal | None,
        coins: Decimal | None,
    ) -> Encashment:
        if encashment.status is not EncashmentStatus.COLLECTED:
            raise CashError("Эти деньги уже посчитаны")
        if encashment.took_bills and bills is None:
            raise CashError("Впишите сумму купюр")
        if encashment.took_coins and coins is None:
            raise CashError("Впишите сумму монет")
        if any(v is not None and v < 0 for v in (bills, coins)):
            raise CashError("Сумма не может быть меньше нуля")

        encashment.bills = bills if encashment.took_bills else None
        encashment.coins = coins if encashment.took_coins else None
        encashment.counted_at = self.clock.now()
        encashment.counted_by_id = user.id
        encashment.status = EncashmentStatus.COUNTED
        await self._close_task(encashment, TaskKind.COUNT_CASH, user)

        total = encashment.counted or Decimal(0)
        self.session.add(
            Task(
                kind=TaskKind.DEPOSIT_CASH,
                title=f"Внести {total:,.0f} ₽ в {BANK}".replace(",", " "),
                description=f"Деньги с «{encashment.machine.name}». "
                f"Отнесите в отделение {BANK} и отметьте, сколько внесли.",
                due_on=None,
                machine_id=encashment.machine_id,
                encashment_id=encashment.id,
            )
        )
        await self.session.flush()
        return encashment

    async def deposit(
        self, encashment: Encashment, user: User, *, amount: Decimal, on: date
    ) -> Encashment:
        if encashment.status is not EncashmentStatus.COUNTED:
            raise CashError("Сначала деньги нужно посчитать")
        if amount <= 0:
            raise CashError("Сумма должна быть больше нуля")
        encashment.deposited = amount
        encashment.deposited_on = on
        encashment.deposited_by_id = user.id
        encashment.status = EncashmentStatus.DEPOSITED
        await self._close_task(encashment, TaskKind.DEPOSIT_CASH, user)
        await self.session.flush()
        return encashment

    async def discard_for_report(self, report: Task) -> None:
        """Called when a report is deleted: an untouched collection goes with it."""
        encashment = await self.for_report(report.id)
        if encashment is None:
            return
        if encashment.status is not EncashmentStatus.COLLECTED:
            raise CashError("Деньги из этого отчёта уже посчитаны — отчёт удалить нельзя")
        tasks = await self.session.scalars(select(Task).where(Task.encashment_id == encashment.id))
        for task in tasks:
            await self.session.delete(task)
        await self.session.delete(encashment)
        await self.session.flush()

    async def cash_in_machine(
        self, machine: Machine, channel: PaymentChannel, until: datetime | None = None
    ) -> Decimal | None:
        """Cash SmartVend saw going into the machine since it was last taken out.

        Unknown (None) when there is no earlier collection and money tracking hasn't been
        started, since there is nothing to count from.
        """
        until = until or self.clock.now()
        took = Encashment.took_bills if channel is PaymentChannel.BILL else Encashment.took_coins
        since = await self.session.scalar(
            select(func.max(Encashment.collected_at)).where(
                Encashment.machine_id == machine.id, took, Encashment.collected_at < until
            )
        )
        if since is None:
            ledger = await self.session.get(Ledger, 1)
            if ledger is None:
                return None
            since = datetime.combine(ledger.opened_on, time.min, tzinfo=self.clock.tz)
        column = TelemetrySale.bill if channel is PaymentChannel.BILL else TelemetrySale.coin
        total = await self.session.scalar(
            select(func.coalesce(func.sum(column), 0)).where(
                TelemetrySale.machine_id == machine.id,
                TelemetrySale.canceled.is_(False),
                TelemetrySale.sold_at > since,
                TelemetrySale.sold_at <= until,
            )
        )
        return Decimal(total or 0)

    async def _close_task(self, encashment: Encashment, kind: TaskKind, user: User) -> None:
        task = await self.session.scalar(
            select(Task).where(
                Task.encashment_id == encashment.id,
                Task.kind == kind,
                Task.status == TaskStatus.OPEN,
            )
        )
        if task is not None:
            task.status = TaskStatus.DONE
            task.completed_at = self.clock.now()
            task.completed_by_id = user.id
