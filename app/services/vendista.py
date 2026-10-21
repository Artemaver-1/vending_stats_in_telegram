from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import DailyRevenue, Machine
from app.domain.enums import PaymentChannel, RevenueSource
from app.integrations.vendista import CardPayment
from app.services.uptime import UptimeEstimator


@dataclass(slots=True)
class MachineImport:
    machine: str
    first_day: date | None = None
    last_day: date | None = None
    amount: Decimal = field(default_factory=Decimal)
    payments: int = 0


@dataclass(slots=True)
class VendistaImportResult:
    covered_through: date | None = None
    machines: list[MachineImport] = field(default_factory=list)
    unknown_terminals: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _Day:
    amount: Decimal = field(default_factory=Decimal)
    count: int = 0


class VendistaImporter:
    """Makes the Vendista export the source of card revenue for every day it covers.

    The terminal's records carry the bank's dates, while SmartVend loses payments when it
    is out of order and books queued ones on the day it reconnects. So for the period of
    the export card revenue is replaced with Vendista's, and SmartVend keeps supplying
    cards only for the days after it. Importing the same file twice changes nothing.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def run(self, payments: Iterable[CardPayment]) -> VendistaImportResult:
        machines = {
            m.vendista_terminal_id: m
            for m in await self.session.scalars(
                select(Machine).where(Machine.vendista_terminal_id.is_not(None))
            )
        }
        result = VendistaImportResult()
        days: dict[int, dict[date, _Day]] = defaultdict(lambda: defaultdict(_Day))

        for payment in payments:
            day = payment.paid_at.astimezone(self.clock.tz).date()
            # The export is cut at one moment for every terminal, so the newest payment
            # in the whole file marks how far it reaches.
            result.covered_through = max(result.covered_through or day, day)
            machine = machines.get(payment.terminal_id)
            if machine is None:
                result.unknown_terminals.add(payment.terminal_id)
                continue
            bucket = days[machine.id][day]
            bucket.amount += payment.amount
            bucket.count += -1 if payment.is_refund else 1

        if result.covered_through is None:
            return result
        for machine in machines.values():
            per_day = days.get(machine.id)
            if not per_day:
                continue
            result.machines.append(await self._replace(machine, per_day, result.covered_through))
        await self.session.flush()
        # Payment days also tell when a machine worked before SmartVend watched it.
        estimator = UptimeEstimator(self.session, self.clock)
        for machine in machines.values():
            await estimator.rebuild(machine)
        return result

    async def _replace(
        self, machine: Machine, per_day: dict[date, _Day], covered_through: date
    ) -> MachineImport:
        first_day = min(per_day)
        await self.session.execute(
            delete(DailyRevenue).where(
                DailyRevenue.machine_id == machine.id,
                DailyRevenue.channel == PaymentChannel.CARD,
                DailyRevenue.day >= first_day,
                DailyRevenue.day <= covered_through,
            )
        )
        rows = [
            {
                "machine_id": machine.id,
                "day": day,
                "channel": PaymentChannel.CARD,
                "amount": bucket.amount,
                "sales_count": max(bucket.count, 0),
                "source": RevenueSource.VENDISTA,
            }
            for day, bucket in sorted(per_day.items())
            if bucket.amount
        ]
        if rows:
            await self.session.execute(insert(DailyRevenue).values(rows))
        machine.vendista_covered_through = max(
            machine.vendista_covered_through or covered_through, covered_through
        )
        return MachineImport(
            machine=machine.name,
            first_day=first_day,
            last_day=max(per_day),
            amount=sum((d.amount for d in per_day.values()), Decimal(0)),
            payments=sum(d.count for d in per_day.values()),
        )
