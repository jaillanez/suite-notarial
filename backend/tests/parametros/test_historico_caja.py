"""Lectura del cuadro histórico de valores de aportes, con un cuadro sintético."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.modules.parametros.historico_caja import (
    CuadroInvalidoError,
    Tramo,
    anteriores_a,
    leer_cuadro,
)

ROTULOS = (
    "Aporte variable por escrituras - \n% s/valor de la escritura",
    "Aporte variable MINIMO por escrituras",
    "Aporte variable MAXIMO por escrituras",
    "Aportes fijos por Actas y Poderes",
    "Aporte fijo por otros actos",
    "Aporte Previsional Mínimo Mensual",
    "Aporte Medico Asistencial Mensual",
)


def _cuadro(ruta: Path, columnas: list[tuple[str, date, list[object]]]) -> Path:
    libro = Workbook()
    ws = libro.active
    assert ws is not None
    ws.title = "cuadro historico"
    ws.append([None, None, "CUADRO RESUMEN"])
    ws.append([])
    ws.append([])
    ws.append([None, None, "Periodo", *[c[0] for c in columnas]])
    ws.append(
        [None, None, "Fecha de vencimiento de \nla obligación de pago", *[c[1] for c in columnas]]
    )
    ws.append([])
    for i, rotulo in enumerate(ROTULOS):
        ws.append([None, None, rotulo, *[c[2][i] for c in columnas]])
    libro.save(ruta)
    return ruta


def _valores(minimo: int, maximo: object, medico: object) -> list[object]:
    return [0.004, minimo, maximo, 100, 500, 1000, medico]


def test_tramos_se_unen_y_cada_valor_rige_hasta_el_cambio(tmp_path: Path) -> None:
    ruta = _cuadro(
        tmp_path / "c.xlsx",
        [
            ("Enero", date(2021, 2, 28), _valores(800, 15000, None)),
            ("Abril (*)", date(2021, 6, 4), _valores(800, 15000, 2850)),
            ("Mayo", date(2021, 6, 28), _valores(1500, "sin maximo", 2850)),
            ("Diciembre", date(2022, 1, 28), _valores(1500, 15000.125, 2850)),
            ("Enero 2022", date(2022, 2, 28), _valores(1500, 1745700, 3000)),
        ],
    )
    tramos, vencimientos, redondeos = leer_cuadro(ruta)
    escritura = [t for t in tramos if t.codigo == "APORTE_ESCRITURA"]
    assert [(t.desde, t.hasta) for t in escritura] == [
        (date(2021, 1, 1), date(2021, 4, 30)),
        (date(2021, 5, 1), date(2021, 11, 30)),
        (date(2021, 12, 1), date(2021, 12, 31)),
        (date(2022, 1, 1), None),
    ]
    assert escritura[0].valores == {
        "porcentaje": Decimal("0.4000"),
        "monto_minimo": Decimal("800.00"),
        "monto_maximo": Decimal("15000.00"),
    }
    assert escritura[1].valores["monto_maximo"] is None  # «sin máximo»
    assert [(r.campo, r.redondeado) for r in redondeos] == [("monto_maximo", Decimal("15000.13"))]
    medico = [t for t in tramos if t.codigo == "APORTE_MEDICO_ASISTENCIAL"]
    assert medico[0].desde == date(2021, 4, 1)  # no existía antes
    assert vencimientos == {
        "2021-01": date(2021, 2, 28),
        "2021-04": date(2021, 6, 4),
        "2021-05": date(2021, 6, 28),
        "2021-12": date(2022, 1, 28),
        "2022-01": date(2022, 2, 28),
    }


def test_solo_lo_anterior_a_lo_que_ya_tiene_el_sistema() -> None:
    v: dict[str, Decimal | None] = {"monto_fijo": Decimal("1.00")}
    tramos = [
        Tramo("A", date(2020, 1, 1), date(2025, 5, 31), v),
        Tramo("A", date(2025, 6, 1), None, v),
        Tramo("B", date(2020, 1, 1), None, v),
    ]
    assert anteriores_a(tramos, {"A": date(2026, 1, 1)}) == [
        Tramo("A", date(2020, 1, 1), date(2025, 5, 31), v),
        Tramo("A", date(2025, 6, 1), date(2025, 12, 31), v),
    ]


def test_cuadro_sin_filas_obligatorias(tmp_path: Path) -> None:
    libro = Workbook()
    assert libro.active is not None
    libro.active.title = "cuadro historico"
    libro.save(tmp_path / "v.xlsx")
    with pytest.raises(CuadroInvalidoError):
        leer_cuadro(tmp_path / "v.xlsx")
