import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.config import Settings
from app.db import Database
from app.domain.enums import UserRole
from app.integrations.smartvend import SmartVendClient, SmartVendError
from app.repositories.telemetry import SyncStateRepository
from app.services.notifications import Messages, Notifier
from app.services.rent import RentService
from app.services.staff import UserService
from app.services.tasks import TaskService
from app.services.telemetry import ConnectivitySync, ControllerRegistry, SalesSync

logger = logging.getLogger(__name__)

# Transitions older than this are recorded silently: after a long downtime of the host
# nobody wants a burst of stale "machine went offline" messages.
ALERT_MAX_AGE = timedelta(hours=3)
# Postgres advisory lock shared by the worker and the "refresh" button in the admin panel,
# so two syncs never rebuild the same days at once.
SYNC_LOCK_ID = 7_310_001
BUSY = "Обновление уже идёт в фоне — загляните через минуту."


class TelemetryJobs:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        client: SmartVendClient,
        notifier: Notifier,
        clock: Clock,
    ) -> None:
        self.settings = settings
        self.db = db
        self.client = client
        self.notifier = notifier
        self.clock = clock

    async def refresh_all(self) -> str | None:
        """Runs both syncs now; returns why it failed, or None. Stops at the first failure.

        Meant for a person waiting on a button, so it doesn't queue behind a background
        sync that may be busy retrying an unreachable server.
        """
        return await self.sync_connectivity(wait=False) or await self.sync_sales(wait=False)

    async def sync_connectivity(self, *, wait: bool = True) -> str | None:
        async def job(session: AsyncSession) -> None:
            await self._refresh_registry(session)
            sync = ConnectivitySync(
                session,
                self.client,
                self.clock,
                history_start=self.settings.smartvend_history_start,
            )
            await sync.run()
            admins = await UserService(session).telegram_ids(UserRole.ADMIN)
            for event in await sync.take_unnotified(ALERT_MAX_AGE):
                await self.notifier.send(admins, Messages.connection(event, self.clock.tz))

        return await self._run(ConnectivitySync.source, job, wait=wait)

    async def sync_sales(self, *, wait: bool = True) -> str | None:
        async def job(session: AsyncSession) -> None:
            await self._refresh_registry(session)
            result = await SalesSync(
                session,
                self.client,
                self.clock,
                history_start=self.settings.smartvend_history_start,
                lookback_days=self.settings.sales_lookback_days,
            ).run()
            logger.info(
                "Sales synced for %s..%s: %d fetched",
                result.first_day,
                result.last_day,
                result.fetched,
            )

        return await self._run(SalesSync.source, job, wait=wait)

    async def _refresh_registry(self, session: AsyncSession) -> None:
        registry = ControllerRegistry(
            session, self.client, self.clock, default_cost=self.settings.default_machine_cost
        )
        await registry.run()

    async def _run(
        self, source: str, job: Callable[[AsyncSession], Awaitable[None]], *, wait: bool = True
    ) -> str | None:
        try:
            async with self.db.session() as session:
                if wait:
                    await session.execute(select(func.pg_advisory_xact_lock(SYNC_LOCK_ID)))
                elif not await session.scalar(select(func.pg_try_advisory_xact_lock(SYNC_LOCK_ID))):
                    return BUSY
                was_failing = (await SyncStateRepository(session).get(source)).last_error
                await job(session)
                admins = await UserService(session).telegram_ids(UserRole.ADMIN)
            if was_failing and source == ConnectivitySync.source:
                await self.notifier.send(admins, "✅ SmartVend снова на связи, данные идут.")
        except Exception as exc:
            logger.exception("Job %s failed", source)
            reason = exc.reason if isinstance(exc, SmartVendError) else "Внутренняя ошибка."
            await self._record_failure(source, exc, reason)
            return reason
        return None

    async def _record_failure(self, source: str, exc: Exception, reason: str) -> None:
        async with self.db.session() as session:
            state = await SyncStateRepository(session).get(source)
            first_failure = state.last_error is None
            # Shown on the admin dashboard; technical details stay in the logs.
            state.last_error = reason[:1000]
            admins = await UserService(session).telegram_ids(UserRole.ADMIN)
        # Both syncs fail together when SmartVend is unreachable; one message is enough.
        if first_failure and source == ConnectivitySync.source:
            await self.notifier.send(
                admins,
                f"⚠️ Не удалось обновить данные SmartVend.\n{reason}\n"
                "Буду пробовать дальше сам и напишу, когда связь вернётся.",
            )


class ServiceJobs:
    """Keeps the weekly inspections going and sends the two reminders before each due date."""

    def __init__(self, db: Database, notifier: Notifier, clock: Clock) -> None:
        self.db = db
        self.notifier = notifier
        self.clock = clock

    async def schedule_inspections(self) -> None:
        async with self.db.session() as session:
            created = await TaskService(session, self.clock).schedule_inspections()
        if created:
            logger.info("Scheduled %d inspections", len(created))

    async def send_reminders(self) -> None:
        today = self.clock.today()
        async with self.db.session() as session:
            users = UserService(session)
            workers = await users.telegram_ids(UserRole.WORKER)
            admins = await users.telegram_ids(UserRole.ADMIN)

            for task in await TaskService(session, self.clock).due_reminders():
                days_left = (task.due_on - today).days
                await self.notifier.send(workers, Messages.task_reminder(task, days_left))
                task.reminded_on = today

            rent = RentService(session, self.clock)
            await rent.sync_accruals()
            for payment in await rent.due_reminders():
                await self.notifier.send(admins, Messages.rent_reminder(payment))
                payment.reminded_on = today
