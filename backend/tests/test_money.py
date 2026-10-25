from decimal import Decimal

import pytest

from app.common.money import to_money, to_rate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.675", Decimal("2.68")),  # con float daría 2.67
        ("2.665", Decimal("2.67")),
        ("0.005", Decimal("0.01")),
        ("-2.675", Decimal("-2.68")),  # HALF_UP redondea alejándose de cero
        ("1.004", Decimal("1.00")),
        ("1234567890123.455", Decimal("1234567890123.46")),
        (10, Decimal("10.00")),
        (Decimal("3.14159"), Decimal("3.14")),
        ("  7.5 ", Decimal("7.50")),
    ],
)
def test_to_money_round_half_up(raw: Decimal | int | str, expected: Decimal) -> None:
    result = to_money(raw)
    assert result == expected
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.12345", Decimal("0.1235")),
        ("0.12344", Decimal("0.1234")),
        ("0.00005", Decimal("0.0001")),
        (1, Decimal("1.0000")),
    ],
)
def test_to_rate_round_half_up(raw: Decimal | int | str, expected: Decimal) -> None:
    result = to_rate(raw)
    assert result == expected
    assert result.as_tuple().exponent == -4


@pytest.mark.parametrize("bad", [2.675, True, None, [1]])
def test_rejects_non_decimal_types(bad: object) -> None:
    with pytest.raises(TypeError):
        to_money(bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_rate(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["abc", "", "NaN", "Infinity"])
def test_rejects_invalid_strings(bad: str) -> None:
    with pytest.raises(ValueError):
        to_money(bad)
