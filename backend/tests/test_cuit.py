import pytest

from app.common.cuit import InvalidCuitError, check_digit, format_cuit, normalize_cuit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20-00000100-8", "20000001008"),
        ("20000001008", "20000001008"),
        ("20.00000100.8", "20000001008"),
        ("33-69345023-9", "33693450239"),  # CUIT institucional público de AFIP
    ],
)
def test_valid_cuits(raw: str, expected: str) -> None:
    assert normalize_cuit(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "20-00000100-9",  # dígito verificador incorrecto
        "21-00000100-8",  # prefijo inexistente
        "2000000100",  # 10 dígitos
        "200000010088",  # 12 dígitos
        "٢٠٠٠٠٠٠١٠٠٨",  # dígitos arábigo-índicos
        "20\u00a000000100\u00a08",  # espacio no separable
        "",
    ],
)
def test_invalid_cuits(raw: str) -> None:
    with pytest.raises(InvalidCuitError):
        normalize_cuit(raw)


def test_check_digit_ten_is_not_assignable() -> None:
    # Cuando el módulo 11 da 10, AFIP no asigna ese número con ese prefijo (usa 23/24/33/34).
    bodies = [f"20{n:08d}" for n in range(200)]
    tens = [b for b in bodies if check_digit(b) is None]
    assert tens
    for body in tens:
        for last in "0123456789":
            with pytest.raises(InvalidCuitError):
                normalize_cuit(body + last)


def test_format_cuit() -> None:
    assert format_cuit("20000001008") == "20-00000100-8"
