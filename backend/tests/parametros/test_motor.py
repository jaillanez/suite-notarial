"""Motor de cálculo: valores sintéticos de prueba, no parámetros oficiales."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.parametros import motor
from app.modules.parametros.catalog import ReglaRedondeo, TipoConcepto
from app.modules.parametros.motor import VigenciaSnapshot


def snap(tipo: TipoConcepto, **values: object) -> VigenciaSnapshot:
    base: dict[str, object] = {
        "vigencia_id": uuid.uuid4(),
        "concepto_codigo": "PRUEBA",
        "tipo": tipo,
        "fecha_desde": date(2026, 1, 1),
        "fecha_hasta": None,
        "porcentaje": None,
        "monto_fijo": None,
        "monto_minimo": None,
        "monto_maximo": None,
        "tasa_mensual": None,
        "dias_gracia": None,
        "regla_redondeo": ReglaRedondeo.HALF_UP,
    }
    base.update(values)
    return VigenciaSnapshot(**base)  # type: ignore[arg-type]


PCT = TipoConcepto.PORCENTUAL_ACTO


@pytest.mark.parametrize(
    ("base", "porcentaje", "minimo", "maximo", "esperado"),
    [
        ("100000.00", "1.5000", None, None, "1500.00"),
        ("1000.00", "1.5000", "500.00", None, "500.00"),  # aplica el mínimo
        ("10000000.00", "1.5000", None, "50000.00", "50000.00"),  # aplica el tope
        ("333.33", "1.0000", None, None, "3.33"),
        ("50.50", "1.0000", None, None, "0.51"),  # 0.505 -> HALF_UP
    ],
)
def test_aporte_porcentual(
    base: str, porcentaje: str, minimo: str | None, maximo: str | None, esperado: str
) -> None:
    v = snap(
        PCT,
        porcentaje=Decimal(porcentaje),
        monto_minimo=Decimal(minimo) if minimo else None,
        monto_maximo=Decimal(maximo) if maximo else None,
    )

    result = motor.aporte_porcentual(Decimal(base), v)

    assert result == Decimal(esperado)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("regla", "esperado"),
    [
        (ReglaRedondeo.HALF_UP, "0.51"),
        (ReglaRedondeo.FLOOR, "0.50"),
        (ReglaRedondeo.CEILING, "0.51"),
    ],
)
def test_regla_de_redondeo(regla: ReglaRedondeo, esperado: str) -> None:
    v = snap(PCT, porcentaje=Decimal("1.0000"), regla_redondeo=regla)

    assert motor.aporte_porcentual(Decimal("50.50"), v) == Decimal(esperado)


def test_aporte_fijo() -> None:
    v = snap(TipoConcepto.FIJO_MENSUAL, monto_fijo=Decimal("12345.67"))

    assert motor.aporte_fijo(v) == Decimal("12345.67")


def test_mora_con_gracia_e_interes_simple() -> None:
    v = snap(TipoConcepto.TASA_MORA, tasa_mensual=Decimal("3.0000"), dias_gracia=10)
    vence = date(2026, 3, 10)

    assert motor.dias_de_mora(vence, date(2026, 3, 20), v) == 0  # dentro de la gracia
    assert motor.dias_de_mora(vence, date(2026, 3, 21), v) == 11
    # 10000 * 3 % / 30 * 30 días = 300.00
    assert motor.interes_mora(Decimal("10000.00"), 30, v) == Decimal("300.00")
    assert motor.interes_mora(Decimal("10000.00"), 0, v) == Decimal("0.00")
    # 1234.56 * 0.03 / 30 * 7 = 8.64192 -> 8.64
    assert motor.interes_mora(Decimal("1234.56"), 7, v) == Decimal("8.64")


def test_tipo_incorrecto_y_valores_invalidos() -> None:
    fijo = snap(TipoConcepto.FIJO_MENSUAL, monto_fijo=Decimal(1))
    pct = snap(PCT, porcentaje=Decimal(1))

    with pytest.raises(motor.MotorError):
        motor.aporte_porcentual(Decimal(100), fijo)
    with pytest.raises(motor.MotorError):
        motor.aporte_porcentual(Decimal(-1), pct)
    with pytest.raises(TypeError):
        motor.aporte_porcentual(1.5, pct)  # type: ignore[arg-type]
