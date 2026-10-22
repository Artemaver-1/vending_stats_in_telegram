import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.base import Base
from app.db.models import Machine
from app.domain.enums import ExpenseCategory, PaymentChannel
from app.domain.periods import iter_months
from app.services.finance import FinanceService

# Columns that are no use to an analyst and shouldn't leave the database.
HIDDEN_COLUMNS = {
    "attachments": {"data"},
    "users": {"telegram_id", "username"},
}
SKIPPED_TABLES = {"attachments"}

AI_PROMPT = """\
Ты — аналитик небольшого вендингового бизнеса: силомеры (уличные автоматы «ударь по груше»,
одна игра 10 ₽) в Челябинске. Во вложении — полная выгрузка базы данных учётной системы.

Как устроены данные:
- Время и даты — по Екатеринбургу (UTC+5). Суммы — в рублях.
- monthly_summary.csv — готовый помесячный отчёт о финансовых результатах по каждому
  силомеру и по бизнесу в целом. Начни с него.
- daily_revenue.csv — выручка по дням, силомерам и способам оплаты (coin — монеты,
  bill — купюры, card — безнал). Источник: telemetry — телеметрия SmartVend, vendista —
  банковский терминал Вендиста (за безнал он точнее), manual — суммы, внесённые вручную за
  время до телеметрии и равномерно разнесённые по рабочим дням.
- telemetry_sales.csv — каждая продажа из телеметрии с точным временем.
- connection_events.csv — когда аппарат терял и восстанавливал связь;
  estimated_uptime.csv — работал ли силомер в дни до телеметрии (оценка по оплатам).
- tasks.csv и inspection_checks.csv — задачи и еженедельные отчёты обслуживания
  (что работало, что нет, комментарии); encashments.csv — инкассации: сколько наличных
  ожидалось по телеметрии, сколько посчитано, сколько внесено в банк.
- expenses.csv, rent_contracts.csv, rent_payments.csv, payouts.csv — расходы, аренда и
  выплаты со счёта. machines.csv и locations.csv — аппараты и точки.

Что нужно:
1. Кратко опиши состояние бизнеса: выручка, прибыль, окупаемость, тренды, сезонность.
2. Сравни силомеры: выручка на рабочий день, доля способов оплаты, простои.
3. Найди, где теряются деньги: простои и их цена, поломки, которые повторяются,
   расхождения наличных при инкассации, аномальные дни.
4. Найди закономерности: дни недели, часы, погода и сезон (по датам), влияние ремонтов.
5. Дай конкретные рекомендации с оценкой эффекта в рублях: что чинить в первую очередь,
   когда обслуживать, какие часы и сезоны использовать, стоит ли и куда ставить третий
   силомер, как изменить цену или аренду.
6. Сделай прогноз выручки и прибыли на 3 и 12 месяцев.
7. Перечисли, каких данных не хватает для более точных выводов, и задай мне уточняющие
   вопросы — после ответов дополни анализ.

Отвечай по-русски, с цифрами и таблицами, отделяй факты из данных от предположений.
"""


class DataExporter:
    """Packs the whole database into a ZIP of CSV files plus a ready prompt for an AI chat."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def build(self) -> tuple[str, bytes]:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for table in Base.metadata.sorted_tables:
                if table.name not in SKIPPED_TABLES:
                    archive.writestr(f"{table.name}.csv", await self._table_csv(table))
            archive.writestr("monthly_summary.csv", await self._monthly_summary())
            archive.writestr("ПРОМТ_ДЛЯ_ИИ.txt", AI_PROMPT)
        name = f"silomery-{self.clock.now():%Y-%m-%d_%H-%M}.zip"
        return name, buffer.getvalue()

    async def _table_csv(self, table: Table) -> str:
        hidden = HIDDEN_COLUMNS.get(table.name, set())
        columns = [c for c in table.columns if c.name not in hidden]
        rows = await self.session.execute(select(*columns))
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([c.name for c in columns])
        for row in rows:
            writer.writerow([self._cell(value) for value in row])
        return out.getvalue()

    async def _monthly_summary(self) -> str:
        finance = await FinanceService.snapshot(self.session)
        today = self.clock.today()
        machines = list(await self.session.scalars(select(Machine).order_by(Machine.name)))
        scopes: list[tuple[str, int | None]] = [("Все силомеры", None)]
        scopes += [(m.name, m.id) for m in machines]

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            ["month", "machine"]
            + [f"revenue_{c.value}" for c in PaymentChannel]
            + ["revenue_total"]
            + [f"expense_{c.value}" for c in ExpenseCategory]
            + ["net_profit"]
        )
        first = await finance.first_day()
        if first is None:
            return out.getvalue()
        for month in iter_months(first, today):
            for name, machine_id in scopes:
                pnl = await finance.monthly_pnl(month, machine_id)
                writer.writerow(
                    [month.strftime("%Y-%m"), name]
                    + [self._cell(pnl.revenue.get(c, Decimal(0))) for c in PaymentChannel]
                    + [self._cell(pnl.total_revenue)]
                    + [self._cell(pnl.expenses.get(c, Decimal(0))) for c in ExpenseCategory]
                    + [self._cell(pnl.net_profit)]
                )
        return out.getvalue()

    def _cell(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.astimezone(self.clock.tz).isoformat(timespec="seconds")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Decimal):
            return format(value, "f")
        return "" if value is None else value
