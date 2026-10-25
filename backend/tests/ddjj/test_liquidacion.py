"""Liquidación pura con los parámetros relevados del sistema actual (actos sintéticos)."""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from app.modules.ddjj.catalog import CategoriaActo
from app.modules.ddjj.liquidacion import (
    ActoALiquidar,
    Liquidacion,
    LiquidacionError,
    liquidar,
)
from app.modules.parametros.catalog import PeriodoTasa, ReglaRedondeo, TipoConcepto
from app.modules.parametros.motor import VigenciaSnapshot
from app.modules.parametros.sistema_actual import CONCEPTOS

D = Decimal


def relevado(codigo: str, fecha: date) -> VigenciaSnapshot:
    concepto = next(c for c in CONCEPTOS if c.codigo == codigo)
    tramo = next(
        t for t in concepto.tramos if t.desde <= fecha and (t.hasta is None or fecha <= t.hasta)
    )
    valores: dict[str, object] = {
        "porcentaje": None,
        "monto_fijo": None,
        "monto_minimo": None,
        "monto_maximo": None,
        "tasa": None,
        "periodo_tasa": None,
        "dias_gracia": None,
    }
    valores.update(tramo.valores)
    return VigenciaSnapshot(
        vigencia_id=uuid.uuid4(),
        concepto_codigo=codigo,
        tipo=concepto.tipo,
        fecha_desde=tramo.desde,
        fecha_hasta=tramo.hasta,
        regla_redondeo=ReglaRedondeo.HALF_UP,
        **valores,  # type: ignore[arg-type]
    )


SEP = date(2026, 9, 1)
VTO_SEP = date(2026, 10, 28)
ESCRITURA = relevado("APORTE_ESCRITURA", SEP)


def escritura(base: str) -> tuple[ActoALiquidar, VigenciaSnapshot]:
    return ActoALiquidar(CategoriaActo.ESCRITURA_CON_VALOR, D(base)), ESCRITURA


def _liquidar(
    actos: Sequence[tuple[ActoALiquidar, VigenciaSnapshot | None]],
    *,
    medicos: int = 1,
    fecha_pago: date = VTO_SEP,
    mora: VigenciaSnapshot | None = None,
) -> Liquidacion:
    return liquidar(
        actos,
        minimo=relevado("APORTE_MINIMO_MENSUAL", SEP),
        medico=relevado("APORTE_MEDICO_ASISTENCIAL", SEP),
        cantidad_aportes_medicos=medicos,
        vencimiento=VTO_SEP,
        fecha_pago=fecha_pago,
        mora=mora,
    )


def test_reproduce_los_totales_de_la_boleta_1069() -> None:
    # Mismos totales que la boleta N° 1069 (09/2026) del sistema actual, con actos sintéticos.
    actos = [
        escritura("100000000.00"),  # 400.000,00
        escritura("120000000.00"),  # 480.000,00
        escritura("26174765.00"),  # 104.699,06
    ]

    liq = _liquidar(actos)

    assert liq.total_protocolos == D("984699.06")
    assert liq.aporte_minimo == D("85932.00")
    assert liq.excedente == D("898767.06")
    assert liq.aporte_medico == D("97000.00")
    assert liq.total_en_termino == D("1081699.06")
    assert liq.interes_mora == D("0.00")
    assert liq.total_a_pagar == D("1081699.06")


def test_categorias_minimo_y_tope() -> None:
    actos: list[tuple[ActoALiquidar, VigenciaSnapshot | None]] = [
        escritura("1000.00"),  # mínimo por escritura: 57.289
        escritura("2000000000.00"),  # tope: 3.482.672
        (
            ActoALiquidar(CategoriaActo.ACTA_O_PODER, D(0)),
            relevado("APORTE_FIJO_ACTAS_PODERES", SEP),
        ),
        (ActoALiquidar(CategoriaActo.OTRO_ACTO, D(0)), relevado("APORTE_FIJO_OTROS_ACTOS", SEP)),
        (ActoALiquidar(CategoriaActo.SIN_EFECTO, D(0)), None),
    ]

    liq = _liquidar(actos)

    assert [a.aporte for a in liq.aportes] == [
        D("57289.00"),
        D("3482672.00"),
        D("9922.00"),
        D("37446.00"),
        D("0.00"),
    ]
    assert liq.aportes[-1].vigencia is None


def test_sin_actos_se_paga_el_minimo() -> None:
    liq = _liquidar([], medicos=2)

    assert liq.total_protocolos == D("0.00")
    assert liq.excedente == D("0.00")
    assert liq.aporte_medico == D("194000.00")
    assert liq.total_en_termino == D("279932.00")


def test_mora_sobre_el_total_en_termino() -> None:
    mora = VigenciaSnapshot(
        vigencia_id=uuid.uuid4(),
        concepto_codigo="TASA_INTERES_MORA",
        tipo=TipoConcepto.TASA_MORA,
        fecha_desde=date(2026, 1, 1),
        fecha_hasta=None,
        porcentaje=None,
        monto_fijo=None,
        monto_minimo=None,
        monto_maximo=None,
        tasa=D("36.5000"),
        periodo_tasa=PeriodoTasa.ANUAL,
        dias_gracia=0,
        regla_redondeo=ReglaRedondeo.HALF_UP,
    )

    liq = _liquidar([escritura("100000000.00")], fecha_pago=date(2026, 11, 7), mora=mora)

    # 400.000 + 97.000 = 497.000; 36,5 % anual = 0,1 % diario; 10 días = 4.970.
    assert liq.dias_mora == 10
    assert liq.interes_mora == D("4970.00")
    assert liq.total_a_pagar == D("501970.00")


def test_es_determinista() -> None:
    actos = [escritura("12345678.91"), escritura("98765432.10")]

    assert _liquidar(actos) == _liquidar(actos)


def test_errores() -> None:
    with pytest.raises(LiquidacionError, match="base imponible"):
        _liquidar([escritura("0")])
    with pytest.raises(LiquidacionError, match="Falta la vigencia"):
        _liquidar([(ActoALiquidar(CategoriaActo.OTRO_ACTO, D(0)), None)])
    with pytest.raises(LiquidacionError, match="tasa de mora"):
        _liquidar([], fecha_pago=date(2026, 11, 1))
