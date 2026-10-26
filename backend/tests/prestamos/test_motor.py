"""Cuadros de amortización contra valores de referencia calculados a mano."""

import itertools
from datetime import date
from decimal import Decimal

import pytest

from app.modules.prestamos.catalog import Sistema
from app.modules.prestamos.motor import (
    MotorPrestamoError,
    afectacion,
    cuota_francesa,
    plan,
    sumar_meses,
)

D = Decimal
INICIO = date(2026, 11, 10)


def test_frances_referencia_12_por_ciento_12_cuotas() -> None:
    # 100.000 al 12 % anual (1 % mensual) en 12 cuotas: cuota = 8.884,88 (tabla financiera).
    cuotas = plan(Sistema.FRANCES, D("100000"), D("12"), 12, INICIO)

    assert cuota_francesa(D("100000"), D("12"), 12) == D("8884.88")
    assert cuotas[0].interes == D("1000.00")
    assert cuotas[0].amortizacion == D("7884.88")
    assert cuotas[1].interes == D("921.15")  # 1 % de 92.115,12
    assert all(c.cuota == D("8884.88") for c in cuotas[:-1])
    # La última ajusta el redondeo: amortiza el saldo exacto y el saldo cierra en cero.
    assert cuotas[-1].saldo_inicial == D("8796.88")
    assert cuotas[-1].interes == D("87.97")
    assert cuotas[-1].cuota == D("8884.85")
    assert cuotas[-1].saldo_final == D("0.00")
    assert sum((c.amortizacion for c in cuotas), D(0)) == D("100000.00")
    assert sum((c.interes for c in cuotas), D(0)) == D("6618.53")


def test_aleman_referencia() -> None:
    # Amortización fija 8.333,33; la última 8.333,37 (100.000 - 11 x 8.333,33).
    cuotas = plan(Sistema.ALEMAN, D("100000"), D("12"), 12, INICIO)

    assert cuotas[0].amortizacion == D("8333.33")
    assert cuotas[0].interes == D("1000.00")
    assert cuotas[0].cuota == D("9333.33")
    assert cuotas[1].interes == D("916.67")  # 1 % de 91.666,67
    assert cuotas[1].cuota == D("9250.00")
    assert cuotas[-1].amortizacion == D("8333.37")
    assert cuotas[-1].interes == D("83.33")
    assert cuotas[-1].cuota == D("8416.70")
    assert [c.cuota for c in cuotas] == sorted((c.cuota for c in cuotas), reverse=True)
    assert sum((c.amortizacion for c in cuotas), D(0)) == D("100000.00")
    assert sum((c.interes for c in cuotas), D(0)) == D("6500.00")
    assert cuotas[-1].saldo_final == D("0.00")


@pytest.mark.parametrize("sistema", list(Sistema))
@pytest.mark.parametrize(
    ("capital", "tna", "n"),
    [
        ("1234567.89", "42.5000", 36),
        ("100000.01", "0", 7),
        ("999.99", "120", 60),
        ("15000000", "68.75", 48),
    ],
)
def test_invariantes(sistema: Sistema, capital: str, tna: str, n: int) -> None:
    cuotas = plan(sistema, D(capital), D(tna), n, date(2027, 1, 31))

    assert len(cuotas) == n
    assert sum((c.amortizacion for c in cuotas), D(0)) == D(capital).quantize(D("0.01"))
    assert cuotas[-1].saldo_final == D("0.00")
    for anterior, siguiente in itertools.pairwise(cuotas):
        assert siguiente.saldo_inicial == anterior.saldo_final
    for c in cuotas:
        assert c.cuota == c.amortizacion + c.interes
        assert c.cuota.as_tuple().exponent == -2


def test_sin_interes_divide_el_capital() -> None:
    cuotas = plan(Sistema.FRANCES, D("1000"), D("0"), 3, INICIO)

    assert [c.cuota for c in cuotas] == [D("333.33"), D("333.33"), D("333.34")]


def test_vencimientos_mensuales_con_fin_de_mes() -> None:
    assert sumar_meses(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert sumar_meses(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert sumar_meses(date(2026, 12, 15), 1) == date(2027, 1, 15)
    cuotas = plan(Sistema.FRANCES, D("1000"), D("10"), 3, date(2027, 1, 31))
    assert [c.vencimiento for c in cuotas] == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
    ]


def test_afectacion_y_errores() -> None:
    assert afectacion(D("8884.88"), D("30000")) == D("29.6163")
    # Borde del tope: 30,00004 % se redondea hacia arriba y no pasa un tope de 30 %.
    assert afectacion(D("30000.04"), D("100000")) == D("30.0001")
    assert afectacion(D("30000.00"), D("100000")) == D("30.0000")
    with pytest.raises(MotorPrestamoError):
        afectacion(D("-1"), D("100"))
    with pytest.raises(MotorPrestamoError):
        plan(Sistema.FRANCES, D("0"), D("10"), 12, INICIO)
    with pytest.raises(MotorPrestamoError):
        plan(Sistema.FRANCES, D("1000"), D("-1"), 12, INICIO)
    with pytest.raises(MotorPrestamoError):
        afectacion(D("100"), D("0"))
