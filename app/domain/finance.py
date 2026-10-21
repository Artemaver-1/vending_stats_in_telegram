from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.domain.enums import ExpenseCategory, PaymentChannel, RentType

ZERO = Decimal("0")
CENT = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class RentTerms:
    rent_type: RentType
    fixed_amount: Decimal | None = None
    revenue_percent: Decimal | None = None

    def charge_for(self, revenue: Decimal) -> Decimal:
        if self.rent_type is RentType.FIXED:
            if self.fixed_amount is None:
                raise ValueError("fixed rent requires fixed_amount")
            return to_money(self.fixed_amount)
        if self.revenue_percent is None:
            raise ValueError("percent rent requires revenue_percent")
        return to_money(revenue * self.revenue_percent / 100)


# Lines of the income statement between revenue and taxes, in display order.
COST_OF_SALES = (
    ExpenseCategory.RENT,
    ExpenseCategory.PARTS,
    ExpenseCategory.REPAIR,
    ExpenseCategory.CONNECTIVITY,
    ExpenseCategory.SMARTVEND,
    ExpenseCategory.STAFF,
    ExpenseCategory.OTHER,
)


@dataclass(slots=True)
class IncomeStatement:
    """Revenue and expenses for the days from `start` to `end`, both inclusive.

    `expenses[RENT]` holds rent from contracts plus any rent entered by hand.
    """

    start: date
    end: date
    revenue: dict[PaymentChannel, Decimal] = field(default_factory=dict)
    expenses: dict[ExpenseCategory, Decimal] = field(default_factory=dict)

    @property
    def period(self) -> date:
        return self.start

    @property
    def total_revenue(self) -> Decimal:
        return sum(self.revenue.values(), ZERO)

    def revenue_share(self, channel: PaymentChannel) -> float:
        total = self.total_revenue
        return float(self.revenue.get(channel, ZERO) / total) if total else 0.0

    @property
    def rent(self) -> Decimal:
        return self.expenses.get(ExpenseCategory.RENT, ZERO)

    @property
    def cost_of_sales(self) -> Decimal:
        return sum((self.expenses.get(c, ZERO) for c in COST_OF_SALES), ZERO)

    @property
    def taxes(self) -> Decimal:
        return self.expenses.get(ExpenseCategory.TAXES, ZERO)

    @property
    def insurance(self) -> Decimal:
        return self.expenses.get(ExpenseCategory.INSURANCE, ZERO)

    @property
    def total_expenses(self) -> Decimal:
        return sum(self.expenses.values(), ZERO)

    @property
    def net_profit(self) -> Decimal:
        return self.total_revenue - self.total_expenses


@dataclass(frozen=True, slots=True)
class PaybackStatus:
    investment: Decimal
    earned: Decimal
    reached_in: date | None

    @property
    def remaining(self) -> Decimal:
        return max(self.investment - self.earned, ZERO)

    @property
    def progress(self) -> float:
        if self.investment <= 0:
            return 1.0
        return min(float(self.earned / self.investment), 1.0)


def calculate_payback(months: Iterable[IncomeStatement], investment: Decimal) -> PaybackStatus:
    """Walks months in chronological order and finds the one where cumulative profit
    first covers the initial investment."""
    earned = ZERO
    reached_in: date | None = None
    for pnl in sorted(months, key=lambda m: m.period):
        earned += pnl.net_profit
        if reached_in is None and earned >= investment:
            reached_in = pnl.period
    return PaybackStatus(investment=investment, earned=earned, reached_in=reached_in)
