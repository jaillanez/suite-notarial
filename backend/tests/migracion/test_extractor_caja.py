"""Extracción desde las planillas de la Caja, con planillas sintéticas (nunca datos reales)."""

import csv
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from openpyxl import Workbook

from app.modules.migracion import extractor_caja as ex

# CUIT sintéticos con dígito verificador correcto.
CUIT_A = "20111111112"
CUIT_B = "27222222228"
CUIT_C = "23333333333"

ENCABEZADO_LISTADO = [
    "REGISTRO",
    "CARÁCTER",
    "APELLIDO DEL NOTARIO",
    "NOMBRE DEL NOTARIO",
    "NOMBRE DEL NOTARIO",
    "CUIL/CUIT/DNI",
    "FECHA DE \nNACIMIENTO",
    "SEXO",
    "ESTADO CIVIL",
    "ALTA",
    None,
    "BAJA",
    "ALTA DE LICENCIA",
    "BAJA DE LICENCIA",
    "ESTADO",
    "LICENCIA",
    "DOMICILIO ESCRIBANIA",
    "TELEFONO ESCRIBANÍA",
    "DOMICILIO PARTICULAR",
    "CORREO ELECTRÓNICO",
]
ENCABEZADO_PAGOS = [
    "TITULO",
    "MATRICULA",
    "EMAIL",
    "NOMBRES",
    "CONCEPTO",
    "REGISTRO",
    "CARÁCTER",
    "CUOTA",
    " ",
    "VTO",
    "PAGO",
    "FECHA PAGO",
    "Mes de Registracion",
    "Intereses",
    "Cargos por Gestión de Cobro",
    "APORTES",
]


def _libro(
    ruta: Path, hoja: str, encabezado: Sequence[object], filas: Sequence[Sequence[object]]
) -> Path:
    libro = Workbook()
    ws = libro.active
    assert ws is not None
    ws.title = hoja
    ws.append(["LISTADO SINTÉTICO"])
    ws.append([])
    ws.append(list(encabezado))
    for fila in filas:
        ws.append(list(fila))
    libro.save(ruta)
    return ruta


def _fila_listado(
    registro: int | None,
    caracter: str | None,
    apellido: str,
    nombre: str,
    cuit: str | None,
    alta: date | None,
    baja: date | None,
    estado: str,
    domicilio: str = "Calle 1",
) -> list[object]:
    return [
        registro,
        caracter,
        apellido,
        nombre,
        f"{apellido},{nombre}",
        cuit,
        date(1970, 1, 1),
        "Femenino",
        "CASADO",
        alta,
        None,
        baja,
        None,
        None,
        estado,
        None,
        domicilio,
        None,
        None,
        "persona@ejemplo.test",
    ]


def _fila_pago(
    matricula: object,
    nombres: str,
    registro: int | None,
    mes: int,
    anio: int,
    pago: float | None,
    fecha_pago: date | None,
    aportes: float | None = None,
) -> list[object]:
    return [
        None,
        matricula,
        None,
        nombres,
        "CUOTA APORTE",
        registro,
        "TITULAR",
        mes,
        anio,
        date(anio, mes, 28),
        pago,
        fecha_pago,
        None,
        0,
        None,
        aportes if aportes is not None else pago,
    ]


def _planillas(tmp_path: Path) -> tuple[Path, Path]:
    listado = _libro(
        tmp_path / "listado.xlsx",
        "TODOS",
        ENCABEZADO_LISTADO,
        [
            # Persona A: adscripta y después titular de otro registro (dos filas, un CUIT).
            _fila_listado(
                10,
                "ADSCRIPTO",
                "PEREZ",
                "ANA",
                "20-11111111-2",
                date(2005, 3, 1),
                date(2010, 2, 1),
                "DESADSCRIPTO",
            ),
            _fila_listado(
                11,
                "TITULAR",
                "PEREZ",
                "ANA",
                "20-11111111-2",
                date(2010, 2, 1),
                None,
                "ACTIVO",
                "Calle 2",
            ),
            # Persona B: «APELLIDO, NOMBRE» en las dos columnas y CUIT con un dígito de menos.
            _fila_listado(
                12, "TITULAR", "GOMEZ, LUCIA", "GOMEZ, LUCIA", "2722222222", None, None, "ACTIVO"
            ),
            # Persona C: histórica, sin CUIT ni alta.
            _fila_listado(None, None, "DIAZ", "JOSE", None, None, None, "FALLECIDO"),
            # Persona D: activa con CUIT pero sin matrícula en ninguna planilla.
            _fila_listado(13, "TITULAR", "SOSA", "RAUL", CUIT_C, date(2020, 1, 1), None, "ACTIVO"),
        ],
    )
    pagos = _libro(
        tmp_path / "pagos.xlsx",
        "aportes",
        ENCABEZADO_PAGOS,
        [
            _fila_pago(41, "PEREZ  Ana", 11, 1, 2025, 1000.5, date(2025, 1, 27)),
            _fila_pago(CUIT_A, "PEREZ  Ana", None, 2, 2025, 11020.4611, date(2025, 2, 27)),
            _fila_pago(7, "GOMEZ  Lucia", 12, 1, 2025, None, None, aportes=-5000),
            _fila_pago(CUIT_B, "GOMEZ  Lucia", 12, 2, 2025, 0, date(2025, 2, 27)),
        ],
    )
    return listado, pagos


def _leer(directorio: Path, nombre: str) -> list[dict[str, str]]:
    with (directorio / f"{nombre}.csv").open(encoding="utf-8") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_nadie_queda_afuera_y_lo_faltante_queda_a_completar(tmp_path: Path) -> None:
    listado, pagos = _planillas(tmp_path)
    salida = tmp_path / "lote"
    ex.guardar(ex.extraer(listado, pagos), salida)

    escribanos = {e["apellido"]: e for e in _leer(salida, "escribanos")}
    assert set(escribanos) == {"PEREZ", "GOMEZ", "DIAZ", "SOSA"}
    assert escribanos["PEREZ"]["matricula"] == "41"
    assert escribanos["PEREZ"]["fecha_matriculacion"] == "2005-03-01"
    assert escribanos["PEREZ"]["estado"] == "ACTIVO"  # la fila más reciente
    assert escribanos["PEREZ"]["numero_documento"] == "11111111"
    # El CUIT inválido del listado se recupera de la planilla de pagos.
    assert escribanos["GOMEZ"]["cuit"] == CUIT_B and escribanos["GOMEZ"]["nombre"] == "LUCIA"
    assert escribanos["GOMEZ"]["matricula"] == "7"
    assert escribanos["DIAZ"]["cuit"] == "" and escribanos["DIAZ"]["fecha_matriculacion"] == ""
    assert escribanos["SOSA"]["matricula"] == ""

    acciones = {(a["codigo_legado"], a["accion"]) for a in _leer(salida, "extraccion")}
    assert (escribanos["SOSA"]["codigo_legado"], "MATRICULA_A_COMPLETAR") in acciones
    assert (escribanos["DIAZ"]["codigo_legado"], "CUIT_A_COMPLETAR") in acciones
    assert (escribanos["GOMEZ"]["codigo_legado"], "CUIT_DE_PAGOS") in acciones


def test_cargos_por_codigo_de_escribano_y_registros_con_titular(tmp_path: Path) -> None:
    listado, pagos = _planillas(tmp_path)
    salida = tmp_path / "lote"
    ex.guardar(ex.extraer(listado, pagos), salida)
    cargos = _leer(salida, "cargos")
    perez = [c for c in cargos if c["escribano"] == f"ESC-{CUIT_A}"]
    assert {(c["numero_registro"], c["cargo"], c["fecha_hasta"]) for c in perez} == {
        ("10", "ADSCRIPTO", "2010-02-01"),
        ("11", "TITULAR", ""),
    }
    registros = {r["numero_registro"]: r for r in _leer(salida, "registros")}
    assert (
        registros["11"]["estado"] == "CON_TITULAR"
        and registros["11"]["domicilio_legal"] == "Calle 2"
    )
    assert registros["10"]["estado"] == "SIN_TITULAR"
    assert registros["10"]["departamento"] == ""  # lo informa la Caja


def test_departamentos_de_la_caja(tmp_path: Path) -> None:
    listado, pagos = _planillas(tmp_path)
    archivo = tmp_path / "registros.csv"
    archivo.write_text(
        "numero_registro;departamento;circunscripcion\n11;Rivadavia;Primera\n", encoding="utf-8"
    )
    registros = {
        r["numero_registro"]: r for r in ex.extraer(listado, pagos, archivo).archivos["registros"]
    }
    assert (registros["11"]["departamento"], registros["11"]["circunscripcion"]) == (
        "Rivadavia",
        "Primera",
    )


def test_boletas_pagos_redondeos_y_registro_deducido(tmp_path: Path) -> None:
    listado, pagos = _planillas(tmp_path)
    salida = tmp_path / "lote"
    ex.guardar(ex.extraer(listado, pagos), salida)
    boletas = {b["codigo_legado"]: b for b in _leer(salida, "boletas")}
    # Fila 4 del Excel: pago con más de dos decimales → redondeado y anotado.
    assert boletas["APD-5"]["importe"] == "11020.46" and boletas["APD-5"]["numero_registro"] == "11"
    redondeos = _leer(salida, "redondeos")
    assert [(r["codigo_legado"], r["original"], r["redondeado"]) for r in redondeos] == [
        ("APD-5", "11020.4611", "11020.46")
    ]
    # Cuota sin pago con el aporte en negativo: deuda impaga por el valor absoluto.
    assert (boletas["APD-6"]["estado"], boletas["APD-6"]["importe"]) == ("IMPAGA", "5000.00")
    assert boletas["APD-4"]["periodo"] == "2025-01"
    pagos_lote = {p["boleta"]: p for p in _leer(salida, "pagos")}
    assert pagos_lote["APD-4"]["importe"] == "1000.50"
    assert "APD-7" not in pagos_lote  # pago en cero: boleta pagada sin movimiento
    acciones = {(a["codigo_legado"], a["accion"]) for a in _leer(salida, "extraccion")}
    assert ("APD-5", "REGISTRO_DEDUCIDO") in acciones
    control = {c["entidad"]: c for c in _leer(salida, "control")}
    assert control["boletas"]["filas"] == "4" and control["pagos"]["importe"] == "12020.96"


def test_valores_y_nombres() -> None:
    assert ex.cuit_valido(CUIT_A) and not ex.cuit_valido("20111111113")
    assert ex.clave_nombre("Pérez,  María José") == "PEREZ MARIA JOSE"
    assert ex.importe(0.1 + 0.2) == ex.importe("0.30000000000000004")
    assert ex.una_fecha("28/02/2025").isoformat() == "2025-02-28"  # type: ignore[union-attr]
    assert ex.una_fecha("sin fecha") is None


def test_consola(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    listado, pagos = _planillas(tmp_path)
    assert (
        ex.main(["--listado", str(listado), "--pagos", str(pagos), "--salida", str(tmp_path / "s")])
        == 0
    )
    assert "escribanos: 4" in capsys.readouterr().out
