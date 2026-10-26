"""Cuadros de amortización (regla FIN): funciones puras sobre `Decimal`, sin base de datos.

- Tasa nominal anual en % (`42.0000` = 42 %); tasa del período = TNA / 12 (mensual).
  TODO(negocio): confirmar con la Caja si la tasa se expresa como TNA (proporcional mensual) o
  como TEM/TEA, y si se suman gastos o seguros a la cuota (costo financiero total).
- Interés sobre saldos: el de cada cuota es el saldo de capital adeudado por la tasa del
  período, redondeado a centavos (ROUND_HALF_UP).
- La última cuota amortiza exactamente el saldo restante: el saldo final queda en $ 0,00 y la
  suma de las amortizaciones es igual al capital, sin diferencias por redondeo.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.common.money import MONEY_QUANT, to_money
from app.modules.prestamos.catalog import Sistema

CERO = Decimal("0.00")
CIEN = Decimal(100)
MESES = Decimal(12)


class MotorPrestamoError(ValueError):
    pass


@dataclass(frozen=True)
class Cuota:
    numero: int
    vencimiento: date
    saldo_inicial: Decimal
    amortizacion: Decimal
    interes: Decimal
    cuota: Decimal
    saldo_final: Decimal


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def tasa_periodica(tna: Decimal) -> Decimal:
    """TNA en % -> tasa mensual como fracción (42 % -> 0,035)."""
    if tna < 0:
        raise MotorPrestamoError("La tasa no puede ser negativa.")
    return tna / CIEN / MESES


def sumar_meses(base: date, meses: int) -> date:
    """Mismo día del mes, o el último día si el mes es más corto (31/01 + 1 -> 28/02)."""
    total = base.month - 1 + meses
    anio, mes = base.year + total // 12, total % 12 + 1
    return date(anio, mes, min(base.day, calendar.monthrange(anio, mes)[1]))


def cuota_francesa(capital: Decimal, tna: Decimal, n: int) -> Decimal:
    """Cuota constante: C · i · (1+i)^n / ((1+i)^n - 1); sin interés, C / n."""
    i = tasa_periodica(tna)
    if i == 0:
        return _centavos(capital / Decimal(n))
    # Precisión holgada para la potencia: el redondeo es uno solo, al final.
    with localcontext() as ctx:
        ctx.prec = 50
        factor = (1 + i) ** n
        return _centavos(capital * i * factor / (factor - 1))


def _validar(capital: Decimal, tna: Decimal, n: int) -> None:
    if capital <= 0:
        raise MotorPrestamoError("El capital tiene que ser mayor que cero.")
    if n <= 0:
        raise MotorPrestamoError("La cantidad de cuotas tiene que ser mayor que cero.")
    if tna < 0:
        raise MotorPrestamoError("La tasa no puede ser negativa.")


def plan(
    sistema: Sistema, capital: Decimal, tna: Decimal, n: int, primer_vencimiento: date
) -> list[Cuota]:
    capital = to_money(capital)
    _validar(capital, tna, n)
    i = tasa_periodica(tna)
    fija_frances = cuota_francesa(capital, tna, n) if sistema is Sistema.FRANCES else CERO
    fija_aleman = _centavos(capital / Decimal(n)) if sistema is Sistema.ALEMAN else CERO
    saldo = capital
    cuotas: list[Cuota] = []
    for k in range(1, n + 1):
        interes = _centavos(saldo * i)
        if k == n:
            amortizacion = saldo
        elif sistema is Sistema.FRANCES:
            amortizacion = fija_frances - interes
        else:
            amortizacion = fija_aleman
        if amortizacion <= 0 or amortizacion > saldo:
            raise MotorPrestamoError("Los parámetros no generan un plan de cuotas válido.")
        cuotas.append(
            Cuota(
                numero=k,
                vencimiento=sumar_meses(primer_vencimiento, k - 1),
                saldo_inicial=saldo,
                amortizacion=amortizacion,
                interes=interes,
                cuota=amortizacion + interes,
                saldo_final=saldo - amortizacion,
            )
        )
        saldo -= amortizacion
    return cuotas


def cuota_maxima(cuotas: list[Cuota]) -> Decimal:
    return max(c.cuota for c in cuotas)


def afectacion(compromiso_mensual: Decimal, ingreso_neto: Decimal) -> Decimal:
    """Porcentaje del ingreso neto mensual comprometido (2 decimales, ROUND_HALF_UP)."""
    if ingreso_neto <= 0:
        raise MotorPrestamoError("El ingreso neto tiene que ser mayor que cero.")
    return (compromiso_mensual * CIEN / ingreso_neto).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
