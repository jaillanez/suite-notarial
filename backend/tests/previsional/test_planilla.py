"""Lectura de la planilla de aportes y puntos (sintética, .xlsx y .xls)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.previsional.planilla import (
    PlanillaInvalidaError,
    interpretar,
    leer_celdas,
    leer_planilla,
    numero,
)
from tests.previsional.conftest import Hoja, celdas, escribir_xls, escribir_xlsx, hoja_basica


def _verificar_basica(ruta: Path) -> None:
    p = leer_planilla(ruta)

    assert [e.anio for e in p.ejercicios] == [1990, 1991]
    e90 = p.ejercicios[0]
    assert (e90.fecha_inicio, e90.fecha_cierre) == (date(1989, 9, 1), date(1990, 8, 31))
    assert e90.total_aportes == Decimal("83466.67")
    assert e90.cantidad_afiliados == Decimal("2.0000")
    assert e90.aporte_medio == Decimal("417.333336")
    assert p.afiliados == 4
    assert [(x.nombre, x.anio, x.aportes, x.puntos) for x in p.puntos] == [
        ("PRUEBA Ana Sintética", 1990, Decimal("82466.67"), Decimal("97.639503")),
        ("PRUEBA Ana Sintética", 1991, Decimal("100.50"), Decimal("50.000000")),
        ("EJEMPLO GÓMEZ Luis", 1990, Decimal("1000.00"), Decimal("102.360497")),
        ("FICTICIO Pedro S.", 1991, Decimal("0.00"), Decimal("150.000000")),
    ]
    # Fila 9: cifras sin nombre. Los pares vacíos o en cero no generan filas.
    assert p.filas_sin_nombre == [9]
    assert p.celdas_vacias == 4
    # Cada redondeo queda informado con su fila, ejercicio, valor original y guardado.
    assert {(r.fila, r.anio, r.campo, r.original, r.guardado) for r in p.redondeos} == {
        (6, 1990, "aportes", Decimal("82466.667256"), Decimal("82466.67")),
        (12, 1990, "total_aportes", Decimal("83466.667256"), Decimal("83466.67")),
    }
    assert p.suma_aportes[1990] == e90.total_aportes
    assert p.suma_puntos[1990] == Decimal("200.000000")


def test_lee_xlsx(planilla_xlsx: Callable[..., Path]) -> None:
    _verificar_basica(planilla_xlsx())


def test_lee_xls(tmp_path: Path) -> None:
    _verificar_basica(escribir_xls(hoja_basica(), tmp_path / "planilla.xls"))


def test_numero_usa_la_representacion_decimal_mas_corta() -> None:
    assert numero(64901.23999999998) == Decimal("64901.23999999998")
    assert numero(0.1) == Decimal("0.1")
    assert numero(7) == Decimal(7)
    assert numero(Decimal("1.5")) == Decimal("1.5")
    with pytest.raises(PlanillaInvalidaError):
        numero(True)
    with pytest.raises(PlanillaInvalidaError):
        numero("12")


def test_puntos_con_mas_de_seis_decimales_se_cuentan() -> None:
    hoja = Hoja(
        anios=[2020],
        afiliados=[("UNO Prueba", [(10, 33.3333333333)]), ("DOS Prueba", [(10, 0.0000001)])],
        totales=[20],
        cantidades=[1.5],
        medios=[1.123456789],
    )
    p = interpretar(celdas(hoja.filas()))

    assert [x.puntos for x in p.puntos] == [Decimal("33.333333"), Decimal("0.000000")]
    assert p.puntos_redondeados == 2
    assert p.ejercicios[0].cantidad_afiliados == Decimal("1.5000")
    assert p.ejercicios[0].aporte_medio == Decimal("1.123457")
    assert any(r.campo == "aporte_medio" for r in p.redondeos)


def test_cifras_menores_que_la_escala_no_generan_fila() -> None:
    hoja = Hoja(anios=[2020], afiliados=[("UNO Prueba", [(0.001, 0.0000001)])], totales=[0])
    p = interpretar(celdas(hoja.filas()))

    assert p.puntos == []
    assert p.celdas_vacias == 1
    assert p.avisos and "escala" in p.avisos[0]


def test_nombre_repetido_se_informa_y_no_se_duplica() -> None:
    hoja = Hoja(
        anios=[2020],
        afiliados=[("UNO  Prueba", [(10, 1)]), ("Uno prueba", [(20, 2)])],
        totales=[30],
    )
    p = interpretar(celdas(hoja.filas()))

    assert len(p.puntos) == 1 and p.puntos[0].aportes == Decimal("10.00")
    assert p.filas_repetidas == [7]


def test_aviso_si_el_cierre_es_de_otro_anio() -> None:
    filas = Hoja(anios=[2020], afiliados=[("UNO Prueba", [(1, 1)])], totales=[1]).filas()
    filas[2][1] = date(2021, 8, 31)
    p = interpretar(celdas(filas))
    assert p.avisos == ["Ejercicio 2020: la fecha de cierre (31/08/2021) es de otro año."]


@pytest.mark.parametrize(
    ("romper", "mensaje"),
    [
        (lambda f: f.pop(0), "Periodo"),
        (lambda f: f[4].__setitem__(2, "OTRA COSA"), "APORTES"),
        (lambda f: f[1].__setitem__(1, "no es fecha"), "Fecha de inicio"),
        (lambda f: f[2].__setitem__(1, date(1980, 1, 1)), "cierre no es posterior"),
        (lambda f: f[0].__setitem__(3, 1990), "repetidos"),
        (lambda f: f[0].__setitem__(1, "mil"), "Año de ejercicio"),
        (lambda f: f[-1].__setitem__(1, None), "faltan"),
        (lambda f: f[5].__setitem__(1, "diez"), "se esperaba un número"),
    ],
)
def test_estructura_invalida(romper: Callable[[list[list[object]]], object], mensaje: str) -> None:
    filas = hoja_basica().filas()
    romper(filas)
    with pytest.raises(PlanillaInvalidaError, match=mensaje):
        interpretar(celdas(filas))


def test_sin_anios_ni_fila_de_cantidad() -> None:
    filas = Hoja(anios=[], afiliados=[]).filas()
    with pytest.raises(PlanillaInvalidaError, match="no tiene años"):
        interpretar(celdas(filas))
    filas = hoja_basica().filas()
    del filas[-3]
    with pytest.raises(PlanillaInvalidaError, match="Cantidad de afiliados"):
        interpretar(celdas(filas))


def test_archivo_inexistente_formato_y_hoja(tmp_path: Path) -> None:
    with pytest.raises(PlanillaInvalidaError, match="No existe"):
        leer_celdas(tmp_path / "no.xls")
    otro = tmp_path / "datos.csv"
    otro.write_text("a;b")
    with pytest.raises(PlanillaInvalidaError, match=r"\.xls o \.xlsx"):
        leer_celdas(otro)
    sin_hoja = escribir_xlsx(hoja_basica(), tmp_path / "otra.xlsx", nombre_hoja="Base")
    with pytest.raises(PlanillaInvalidaError, match="Actualizada"):
        leer_celdas(sin_hoja)
