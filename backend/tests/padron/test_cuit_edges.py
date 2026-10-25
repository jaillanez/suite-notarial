"""CUIT Módulo 11: casos borde del dígito verificador 10 (reasignación AFIP a 23/33)."""

import pytest

from app.common.cuit import InvalidCuitError, check_digit, normalize_cuit


def _bodies_with_ten(prefix: str) -> list[str]:
    return [
        b
        for b in (f"{prefix}{n:08d}" for n in range(30_000_000, 30_000_400))
        if check_digit(b) is None
    ]


def test_male_prefix_twenty_with_ten_moves_to_23_with_9() -> None:
    bodies = _bodies_with_ten("20")
    assert bodies
    for body in bodies:
        dni = body[2:]
        with pytest.raises(InvalidCuitError):
            normalize_cuit(f"{body}9")  # el 20-…-9 no existe: AFIP lo reasigna
        assert normalize_cuit(f"23{dni}9") == f"23{dni}9"


def test_female_prefix_27_with_ten_moves_to_23_with_4() -> None:
    bodies = _bodies_with_ten("27")
    assert bodies
    for body in bodies:
        dni = body[2:]
        assert normalize_cuit(f"23{dni}4") == f"23{dni}4"


def test_company_prefix_30_with_ten_moves_to_33_with_9() -> None:
    bodies = _bodies_with_ten("30")
    assert bodies
    for body in bodies:
        assert normalize_cuit(f"33{body[2:]}9") == f"33{body[2:]}9"


def test_check_digit_eleven_becomes_zero() -> None:
    bodies = [f"20{n:08d}" for n in range(30_000_000, 30_000_400)]
    zeros = [b for b in bodies if check_digit(b) == 0]
    assert zeros
    assert normalize_cuit(zeros[0] + "0") == zeros[0] + "0"
