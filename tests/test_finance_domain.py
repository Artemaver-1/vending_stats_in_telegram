from datetime import date
from decimal import Decimal

import pytest

from app.domain.enums import ExpenseCategory, PaymentChannel, RentType
from app.domain.finance import IncomeStatement, RentTerms, calculate_payback
from app.domain.periods import iter_months, next_month, previous_month


def test_fixed_rent_ignores_revenue() -> None:
    terms = RentTerms(RentType.FIXED, fixed_amount=Decimal("15000"))
    assert terms.charge_for(Decimal("90000")) == Decimal("15000.00")


def test_percent_rent_is_rounded_to_kopecks() -> None:
    terms = RentTerms(RentType.PERCENT, revenue_percent=Decimal("12.5"))
    assert terms.charge_for(Decimal("1000.03")) == Decimal("125.00")


def test_rent_without_terms_is_rejected() -> None:
    with pytest.raises(ValueError):
        RentTerms(RentType.PERCENT).charge_for(Decimal("100"))


def month(m: int, **kwargs: object) -> IncomeStatement:
    return IncomeStatement(date(2026, m, 1), date(2026, m, 28), **kwargs)  # type: ignore[arg-type]


def test_income_statement_lines() -> None:
    statement = month(
        9,
        revenue={PaymentChannel.CARD: Decimal("30000"), PaymentChannel.COIN: Decimal("10000")},
        expenses={
            ExpenseCategory.RENT: Decimal("10000"),
            ExpenseCategory.REPAIR: Decimal("3500"),
            ExpenseCategory.TAXES: Decimal("2400"),
            ExpenseCategory.INSURANCE: Decimal("600"),
        },
    )
    assert statement.total_revenue == Decimal("40000")
    assert statement.revenue_share(PaymentChannel.CARD) == pytest.approx(0.75)
    assert statement.revenue_share(PaymentChannel.BILL) == 0
    assert statement.cost_of_sales == Decimal("13500")
    assert (statement.taxes, statement.insurance) == (Decimal("2400"), Decimal("600"))
    assert statement.net_profit == Decimal("23500")


def test_empty_statement_has_no_shares() -> None:
    assert month(9).revenue_share(PaymentChannel.CARD) == 0


def test_payback_month_is_first_month_cumulative_profit_covers_investment() -> None:
    months = [month(m, revenue={PaymentChannel.CARD: Decimal("100000")}) for m in (7, 5, 6)]
    status = calculate_payback(months, Decimal("250000"))
    assert status.reached_in == date(2026, 7, 1)
    assert status.remaining == 0


def test_payback_not_reached() -> None:
    months = [month(5, revenue={PaymentChannel.CARD: Decimal("80000")})]
    status = calculate_payback(months, Decimal("320000"))
    assert status.reached_in is None
    assert status.remaining == Decimal("240000")
    assert status.progress == pytest.approx(0.25)


def test_month_arithmetic_wraps_years() -> None:
    assert next_month(date(2026, 12, 20)) == date(2027, 1, 1)
    assert previous_month(date(2027, 1, 5)) == date(2026, 12, 1)
    assert list(iter_months(date(2026, 11, 30), date(2027, 1, 2))) == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2027, 1, 1),
    ]
