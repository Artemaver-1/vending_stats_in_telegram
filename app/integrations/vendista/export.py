import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

# The personal account exports times in Moscow time regardless of where the terminal is.
EXPORT_TZ = ZoneInfo("Europe/Moscow")

# A refunded sale stays positive and the refund comes as a separate negative row,
# so summing these three statuses gives the money that actually stayed with us.
COUNTED_STATUSES = frozenset(
    {
        "Успешная транзакция снятия денег",
        "Успешная транзакция снятия денег, по которой впоследствии произошел возврат",
        "Успешный возврат денег",
    }
)


class VendistaExportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CardPayment:
    transaction_id: str
    terminal_id: str
    paid_at: datetime
    amount: Decimal

    @property
    def is_refund(self) -> bool:
        return self.amount < 0


def read_transactions(data: bytes) -> Iterator[CardPayment]:
    """Parses the "Транзакции" CSV export from the Vendista personal account.

    Failed payments and failed refunds are skipped; card numbers are never read.
    """
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    required = {"ID транзакции", "Дата и время", "ID терминала", "Сумма, ₽", "Статус"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise VendistaExportError("Это не выгрузка транзакций Вендисты")

    for line, row in enumerate(reader, start=2):
        if row["Статус"] not in COUNTED_STATUSES:
            continue
        try:
            paid_at = datetime.strptime(row["Дата и время"], "%d.%m.%Y %H:%M:%S")
            amount = Decimal(row["Сумма, ₽"].replace("\xa0", "").replace(" ", "").replace(",", "."))
        except (ValueError, InvalidOperation) as exc:
            raise VendistaExportError(
                f"Строка {line}: не удалось разобрать дату или сумму"
            ) from exc
        yield CardPayment(
            transaction_id=row["ID транзакции"],
            terminal_id=row["ID терминала"].strip(),
            paid_at=paid_at.replace(tzinfo=EXPORT_TZ),
            amount=amount,
        )
