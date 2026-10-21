from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyRevenue, Machine, TelemetrySale
from app.domain.enums import PaymentChannel, RevenueSource
from app.integrations.vendista import VendistaExportError, read_transactions
from app.services.vendista import VendistaImporter
from tests.helpers import TZ, FixedClock

HEADER = "№;ID транзакции;Дата и время;TID;ID терминала;Сумма, ₽;Номер карты;Статус"


def export(*rows: str) -> bytes:
    return ("﻿" + "\n".join([HEADER, *rows]) + "\n").encode()


OK = "Успешная транзакция снятия денег"
REFUNDED = "Успешная транзакция снятия денег, по которой впоследствии произошел возврат"


def test_only_money_that_stayed_is_read() -> None:
    data = export(
        f"1;11;20.10.2026 19:26:01;E1;131508;10,00;00****0000;{OK}",
        "2;12;20.10.2026 19:27:00;E1;131508;10,00;00****0000;Неуспешная транзакция снятия денег",
        f"3;13;20.10.2026 19:28:00;E1;131508;10,00;00****0000;{REFUNDED}",
        "4;14;20.10.2026 19:29:00;E1;131508;-10,00;00****0000;Успешный возврат денег",
        "5;15;20.10.2026 19:30:00;E1;131508;-10,00;00****0000;Неуспешный возврат денег",
    )
    payments = list(read_transactions(data))
    assert [p.transaction_id for p in payments] == ["11", "13", "14"]
    assert sum(p.amount for p in payments) == Decimal("10")
    assert payments[2].is_refund


def test_times_are_moscow() -> None:
    (payment,) = read_transactions(export(f"1;1;20.10.2026 23:30:00;E1;1;10,00;x;{OK}"))
    # 23:30 in Moscow is already 01:30 next day in Chelyabinsk.
    assert payment.paid_at.astimezone(TZ) == datetime(2026, 10, 21, 1, 30, tzinfo=TZ)


def test_foreign_file_is_rejected() -> None:
    with pytest.raises(VendistaExportError):
        list(read_transactions(b"date,amount\n2026-10-01,10\n"))


@pytest.fixture
async def machines(session: AsyncSession) -> dict[str, Machine]:
    pushkina = Machine(name="Пушкина", purchase_cost=Decimal(1), vendista_terminal_id="131508")
    dynamo = Machine(name="Динамо", purchase_cost=Decimal(1), vendista_terminal_id="137465")
    session.add_all([pushkina, dynamo])
    await session.flush()
    # SmartVend took over Pushkina's cards on 3 June 2025.
    session.add(
        TelemetrySale(
            id="s1",
            machine_id=pushkina.id,
            sold_at=datetime(2025, 6, 3, 10, tzinfo=UTC),
            bill=Decimal(0),
            coin=Decimal(0),
            card=Decimal(10),
        )
    )
    await session.flush()
    return {"pushkina": pushkina, "dynamo": dynamo}


async def test_import_fills_days_before_telemetry_only(
    session: AsyncSession, machines: dict[str, Machine]
) -> None:
    data = export(
        f"1;1;20.05.2024 12:00:00;E1;131508;10,00;x;{OK}",
        f"2;2;20.05.2024 13:00:00;E1;131508;10,00;x;{OK}",
        f"3;3;02.06.2025 12:00:00;E1;131508;10,00;x;{OK}",
        f"4;4;03.06.2025 12:00:00;E1;131508;10,00;x;{OK}",
        f"5;5;02.07.2024 12:00:00;E2;137465;10,00;x;{OK}",
        f"6;6;02.07.2024 12:00:00;E3;999999;10,00;x;{OK}",
    )
    importer = VendistaImporter(session, FixedClock(datetime(2026, 10, 21, tzinfo=TZ)))
    result = await importer.run(read_transactions(data))
    # Same file once more must not double anything.
    await importer.run(read_transactions(data))

    by_name = {m.machine: m for m in result.machines}
    assert (by_name["Пушкина"].payments, by_name["Пушкина"].skipped) == (3, 1)
    assert by_name["Пушкина"].last_day == date(2025, 6, 2)
    assert result.unknown_terminals == {"999999"}

    rows = (
        await session.scalars(
            select(DailyRevenue).where(DailyRevenue.source == RevenueSource.VENDISTA)
        )
    ).all()
    assert sorted((r.machine_id, r.day, r.amount, r.sales_count) for r in rows) == sorted(
        [
            (machines["pushkina"].id, date(2024, 5, 20), Decimal("20"), 2),
            (machines["pushkina"].id, date(2025, 6, 2), Decimal("10"), 1),
            (machines["dynamo"].id, date(2024, 7, 2), Decimal("10"), 1),
        ]
    )
    assert {r.channel for r in rows} == {PaymentChannel.CARD}
