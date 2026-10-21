from datetime import date
from decimal import Decimal

from app.domain.reconciliation import DiscrepancyKind, daily_series, find_discrepancies


def series(vendista: list[int], smartvend: list[int]) -> list:
    first = date(2026, 4, 1)
    days = [date(2026, 4, i + 1) for i in range(len(vendista))]
    return daily_series(
        {d: Decimal(v) for d, v in zip(days, vendista, strict=True)},
        {d: Decimal(s) for d, s in zip(days, smartvend, strict=True)},
        first,
        days[-1],
    )


def test_matching_days_have_no_discrepancies() -> None:
    assert find_discrepancies(series([10, 20, 0, 30], [10, 20, 0, 30])) == []


def test_queued_payments_booked_on_reconnect_are_a_shift() -> None:
    (episode,) = find_discrepancies(series([10, 20, 30, 0, 0], [0, 0, 60, 0, 0]))
    assert episode.kind is DiscrepancyKind.SHIFTED
    assert (episode.first, episode.last) == (date(2026, 4, 1), date(2026, 4, 3))
    assert episode.balance == 0 and episode.moved == Decimal(30)


def test_smartvend_out_of_order() -> None:
    days = series([10, 20, 30] + [0] * 7, [0] * 10)
    (episode,) = find_discrepancies(days)
    assert episode.kind is DiscrepancyKind.SMARTVEND_DOWN
    assert episode.last == date(2026, 4, 3)
    assert episode.balance == Decimal(60)


def test_partial_loss_and_extra_money() -> None:
    lost, extra = find_discrepancies(
        series([10, 20, 0, 0, 0, 0, 0, 0, 0, 0, 10], [10, 10, 0, 0, 0, 0, 0, 0, 0, 0, 30])
    )
    assert lost.kind is DiscrepancyKind.SMARTVEND_PARTIAL and lost.balance == Decimal(10)
    assert extra.kind is DiscrepancyKind.SMARTVEND_EXTRA and extra.balance == Decimal(-20)
