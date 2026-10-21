from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import Machine
from app.domain.enums import PaymentChannel, RevenueSource
from app.integrations.vendista import CardPayment
from app.repositories.telemetry import DailyRevenueWriter, TelemetrySaleRepository


@dataclass(slots=True)
class MachineImport:
    machine: str
    first_day: date | None = None
    last_day: date | None = None
    amount: Decimal = field(default_factory=Decimal)
    payments: int = 0
    # Card payments from days SmartVend already covers; they stay out to avoid counting twice.
    skipped: int = 0


@dataclass(slots=True)
class VendistaImportResult:
    machines: list[MachineImport] = field(default_factory=list)
    unknown_terminals: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _Day:
    amount: Decimal = field(default_factory=Decimal)
    count: int = 0


class VendistaImporter:
    """Loads card revenue from a Vendista export for the days before SmartVend telemetry.

    Once a machine reports through SmartVend its card sales come from there, so only the
    days before the machine's first telemetry sale are taken from the export. Importing
    the same file again replaces what the previous import wrote.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock
        self.sales = TelemetrySaleRepository(session)
        self.revenue = DailyRevenueWriter(session)

    async def run(self, payments: Iterable[CardPayment]) -> VendistaImportResult:
        machines = {
            m.vendista_terminal_id: m
            for m in await self.session.scalars(
                select(Machine).where(Machine.vendista_terminal_id.is_not(None))
            )
        }
        result = VendistaImportResult()
        days: dict[int, dict[date, _Day]] = defaultdict(lambda: defaultdict(_Day))
        reports: dict[int, MachineImport] = {}
        cutoffs: dict[int, date | None] = {}

        for payment in payments:
            machine = machines.get(payment.terminal_id)
            if machine is None:
                result.unknown_terminals.add(payment.terminal_id)
                continue
            if machine.id not in cutoffs:
                first_telemetry = await self.sales.first_sale_at(machine.id)
                cutoffs[machine.id] = (
                    first_telemetry.astimezone(self.clock.tz).date() if first_telemetry else None
                )
                reports[machine.id] = MachineImport(machine=machine.name)

            day = payment.paid_at.astimezone(self.clock.tz).date()
            cutoff = cutoffs[machine.id]
            if cutoff is not None and day >= cutoff:
                reports[machine.id].skipped += 1
                continue
            bucket = days[machine.id][day]
            bucket.amount += payment.amount
            bucket.count += -1 if payment.is_refund else 1

        for machine_id, report in reports.items():
            per_day = days[machine_id]
            if not per_day:
                result.machines.append(report)
                continue
            report.first_day, report.last_day = min(per_day), max(per_day)
            report.amount = sum((d.amount for d in per_day.values()), Decimal(0))
            report.payments = sum(d.count for d in per_day.values())
            rows = [
                {
                    "machine_id": machine_id,
                    "day": day,
                    "channel": PaymentChannel.CARD,
                    "amount": bucket.amount,
                    "sales_count": max(bucket.count, 0),
                    "source": RevenueSource.VENDISTA,
                }
                for day, bucket in sorted(per_day.items())
                if bucket.amount
            ]
            await self.revenue.replace_days(
                report.first_day,
                report.last_day,
                RevenueSource.VENDISTA,
                rows,
                machine_id=machine_id,
            )
            result.machines.append(report)

        await self.session.flush()
        return result
