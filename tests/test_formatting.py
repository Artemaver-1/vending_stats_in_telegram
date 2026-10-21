from decimal import Decimal

import pytest

from app.formatting import rub


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0"), "0 ₽"),
        (Decimal("320000"), "320 000 ₽"),
        (Decimal("1234.5"), "1 234,50 ₽"),
        (Decimal("-12000"), "−12 000 ₽"),
    ],
)
def test_rub(value: Decimal, expected: str) -> None:
    assert rub(value) == expected
