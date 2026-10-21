from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import Clock
from app.db.models import Machine, PaymentAlert, TelemetrySale
from app.domain.enums import PaymentChannel

# A method that took no payments for this long while the machine kept selling is suspect.
QUIET_PERIOD = timedelta(days=2)


# A stray payment can still slip through a failing acceptor: one, or 1% of the sales.
def allowed_hits(sales: int) -> int:
    return max(1, sales // 100)


# "Kept selling": fewer sales than this in the quiet period prove nothing.
MIN_SALES = 10
# Methods a machine's customers simply don't use aren't worth an alert.
USED_LOOKBACK = timedelta(days=60)
MIN_PAST_USES = 10
# The two days are counted back from the machine's latest known sale, so a delay in
# SmartVend's data doesn't hide a broken acceptor. A machine that hasn't sold for longer
# than this is standing idle, which the downtime banner already covers.
IDLE_AFTER = timedelta(days=7)


@dataclass(slots=True)
class WatchResult:
    raised: list[PaymentAlert] = field(default_factory=list)
    cleared: list[PaymentAlert] = field(default_factory=list)


class PaymentWatch:
    """Notices a payment method nobody has paid with for two days while the machine
    kept selling by other methods, and clears it once payments come through again."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def open_alerts(self, machine_id: int | None = None) -> list[PaymentAlert]:
        stmt = select(PaymentAlert).where(PaymentAlert.resolved_at.is_(None))
        if machine_id is not None:
            stmt = stmt.where(PaymentAlert.machine_id == machine_id)
        result = await self.session.scalars(
            stmt.options(selectinload(PaymentAlert.machine)).order_by(PaymentAlert.raised_at)
        )
        return list(result)

    async def run(self) -> WatchResult:
        result = WatchResult()
        open_alerts = {(a.machine_id, a.channel): a for a in await self.open_alerts()}
        now = self.clock.now()
        machines = await self.session.scalars(select(Machine).where(Machine.is_active))
        for machine in machines:
            latest = await self._latest_sale(machine)
            if latest is None or now - latest > IDLE_AFTER:
                continue
            since = latest - QUIET_PERIOD
            recent = await self._count(machine, since)
            for channel in PaymentChannel:
                alert = open_alerts.get((machine.id, channel))
                hits = await self._count(machine, since, channel)
                if alert is not None:
                    if hits > allowed_hits(recent):
                        alert.resolved_at = now
                        result.cleared.append(alert)
                    else:
                        alert.recent_sales, alert.recent_hits = recent, hits
                    continue
                if machine.is_broken or recent < MIN_SALES or hits > allowed_hits(recent):
                    continue
                if await self._count(machine, latest - USED_LOOKBACK, channel) < MIN_PAST_USES:
                    continue
                alert = PaymentAlert(
                    machine_id=machine.id,
                    channel=channel,
                    raised_at=now,
                    recent_sales=recent,
                    recent_hits=hits,
                )
                alert.machine = machine
                self.session.add(alert)
                result.raised.append(alert)
        await self.session.flush()
        return result

    async def _latest_sale(self, machine: Machine) -> datetime | None:
        return await self.session.scalar(
            select(func.max(TelemetrySale.sold_at)).where(
                TelemetrySale.machine_id == machine.id, TelemetrySale.canceled.is_(False)
            )
        )

    async def _count(
        self, machine: Machine, since: datetime, channel: PaymentChannel | None = None
    ) -> int:
        conditions = [
            TelemetrySale.machine_id == machine.id,
            TelemetrySale.canceled.is_(False),
            TelemetrySale.sold_at >= since,
        ]
        if channel is not None:
            column = {
                PaymentChannel.BILL: TelemetrySale.bill,
                PaymentChannel.COIN: TelemetrySale.coin,
                PaymentChannel.CARD: TelemetrySale.card,
            }[channel]
            conditions.append(column > 0)
        count = await self.session.scalar(select(func.count()).where(*conditions))
        return count or 0
