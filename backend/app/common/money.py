"""Helpers monetarios (regla FIN).

Todo monto o tasa del sistema pasa por estas funciones. Nunca se usa `float`:
los valores de punto flotante se rechazan explícitamente para no arrastrar
errores de representación binaria.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.0001")

type DecimalInput = Decimal | int | str


def _to_decimal(value: DecimalInput) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise TypeError(f"Tipo no permitido para valores monetarios: {type(value).__name__}")
    try:
        result = Decimal(value.strip()) if isinstance(value, str) else Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Valor decimal inválido: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Valor decimal no finito: {value!r}")
    return result


def to_money(value: DecimalInput) -> Decimal:
    """Cuantiza a 2 decimales con ROUND_HALF_UP (columna `Numeric(15,2)`)."""
    return _to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def to_rate(value: DecimalInput) -> Decimal:
    """Cuantiza a 4 decimales con ROUND_HALF_UP (columnas `Numeric(18,4)` / `Numeric(6,4)`)."""
    return _to_decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def format_pesos(monto: Decimal) -> str:
    """`$ 1.081.699,06`: formato argentino para textos (boleta, correos), sin pasar por float."""
    signo = "-" if monto < 0 else ""
    entero, _, centavos = f"{abs(monto):.2f}".partition(".")
    grupos: list[str] = []
    while entero:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    return f"{signo}$ {'.'.join(grupos)},{centavos}"
