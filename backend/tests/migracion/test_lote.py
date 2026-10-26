"""Valores del origen, formato del lote y validación (sin base de datos)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.migracion import formato, homologacion, valores
from app.modules.migracion.catalog import Entidad, Severidad
from app.modules.migracion.validacion import Existentes, validar
from app.modules.migracion.valores import ValorInvalidoError


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("1.234,50", "1234.50"),
        ("1234,5", "1234.50"),
        ("1234.50", "1234.50"),
        ("1,234.50", "1234.50"),
        ("$ 1.234", "1234.00"),
        ("1.234.567", "1234567.00"),
        ("0,10", "0.10"),
        ("-15,00", "-15.00"),
        ("1234.5000", "1234.50"),
    ],
)
def test_importe_exacto(texto: str, esperado: str) -> None:
    assert valores.importe(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", ["123456.789", "12,3456", "abc", "", "1.2.3,4,5"])
def test_importe_no_se_adivina(texto: str) -> None:
    """Más de dos decimales (típico de un float del origen) no se redondea: se rechaza."""
    with pytest.raises(ValorInvalidoError):
        valores.importe(texto)


def test_fechas_y_periodos() -> None:
    assert valores.fecha("2026-09-14") == date(2026, 9, 14)
    assert valores.fecha("14/09/2026") == date(2026, 9, 14)
    assert valores.fecha("14-09-2026 00:00:00") == date(2026, 9, 14)
    with pytest.raises(ValorInvalidoError):
        valores.fecha("31/02/2026")
    with pytest.raises(ValorInvalidoError):
        valores.fecha("septiembre 2026")
    assert valores.periodo("09/2026") == valores.periodo("202609") == "2026-09"
    with pytest.raises(ValorInvalidoError):
        valores.periodo("13/2026")


def test_lote_incompleto(tmp_path: Path, lote: Callable[..., Path]) -> None:
    directorio = lote()
    (directorio / "pagos.csv").unlink()
    with pytest.raises(formato.FormatoInvalidoError, match=r"Falta pagos\.csv"):
        formato.leer_lote(directorio)

    directorio = lote("sin-columna")
    texto = (directorio / "escribanos.csv").read_text(encoding="utf-8")
    (directorio / "escribanos.csv").write_text(texto.replace("cuit;", "c_u_i_t;", 1))
    with pytest.raises(formato.FormatoInvalidoError, match="faltan las columnas cuit"):
        formato.leer_lote(directorio)


def test_codificacion_y_separador_del_origen(lote: Callable[..., Path]) -> None:
    """Un sistema viejo suele exportar en Windows-1252 y con comas: se detecta y se informa."""
    directorio = lote()
    archivo = directorio / "registros.csv"
    texto = archivo.read_text(encoding="utf-8").replace(";", ",").replace("Ficticia", "Ñandú")
    archivo.write_bytes(texto.encode("cp1252"))
    leido = formato.leer_lote(directorio)
    assert leido.codificaciones["registros.csv"] == "cp1252"
    assert leido.filas[Entidad.REGISTROS][0].datos["domicilio_legal"].startswith("Calle Ñandú")


def test_huella_identifica_el_lote(lote: Callable[..., Path]) -> None:
    a, b = lote("a"), lote("b")
    assert formato.leer_lote(a).huella == formato.leer_lote(b).huella
    (b / "control.csv").write_text("entidad;filas;importe\n", encoding="utf-8")
    with pytest.raises(formato.FormatoInvalidoError, match="faltan los totales"):
        formato.leer_lote(b)


def test_lote_limpio_sin_observaciones(lote: Callable[..., Path]) -> None:
    st = validar(formato.leer_lote(lote()), homologacion.cargar(), Existentes())
    assert st.observaciones == []
    assert st.bloqueantes() == 0
    assert st.leidas["boletas"] == len(st.boletas)


def test_defectos_observados_con_su_cascada(lote: Callable[..., Path]) -> None:
    st = validar(formato.leer_lote(lote(defectos=True)), homologacion.cargar(), Existentes())
    codigos = {o.codigo for o in st.observaciones}
    assert {
        "VALOR_INVALIDO",  # CUIT con dígito inválido e importe con 3 decimales
        "MATRICULA_DUPLICADA",
        "SIN_HOMOLOGACION",
        "TITULARES_MULTIPLES",
        "CARGOS_VIGENTES_MULTIPLES",
        "ESCRIBANO_NO_MIGRADO",  # cargos de los escribanos rechazados
        "REGISTRO_NO_MIGRADO",  # boletas del registro con estado sin homologar
        "BOLETA_NO_MIGRADA",  # pagos de boletas rechazadas o inexistentes
    } <= codigos
    # Las dos filas con la misma matrícula se observan (no se elige una).
    assert sum(o.codigo == "MATRICULA_DUPLICADA" for o in st.observaciones) == 2
    # Cada fila leída está cargable o rechazada, nunca en el limbo.
    for entidad in Entidad:
        cargables = len(getattr(st, entidad.value))
        assert st.leidas[entidad.value] == cargables + st.rechazadas[entidad.value]
    # Sin datos personales en las observaciones.
    texto = " ".join(o.mensaje for o in st.observaciones)
    assert not any(ch.isdigit() for ch in texto.replace("123456.789", ""))


def test_choques_con_la_suite(lote: Callable[..., Path]) -> None:
    lote_leido = formato.leer_lote(lote())
    primera = lote_leido.filas[Entidad.ESCRIBANOS][0].datos
    existentes = Existentes(
        cuits=frozenset({primera["cuit"]}),
        matriculas=frozenset({int(lote_leido.filas[Entidad.ESCRIBANOS][1].datos["matricula"])}),
        registros=frozenset({int(lote_leido.filas[Entidad.REGISTROS][0].datos["numero_registro"])}),
    )
    st = validar(lote_leido, homologacion.cargar(), existentes)
    codigos = {o.codigo for o in st.observaciones if o.severidad is Severidad.BLOQUEANTE}
    assert {"CUIT_EXISTENTE", "MATRICULA_EXISTENTE", "REGISTRO_EXISTENTE"} <= codigos


def test_homologacion_invalida(tmp_path: Path) -> None:
    ruta = tmp_path / "h.json"
    ruta.write_text('{"estado_escribano": {"A": "VIGENTE"}}', encoding="utf-8")
    with pytest.raises(homologacion.HomologacionInvalidaError, match="no es un valor"):
        homologacion.cargar(ruta)
    assert homologacion.cargar().es_ejemplo is True


def test_la_tabla_de_ejemplo_no_deja_de_serlo_por_una_marca(tmp_path: Path) -> None:
    import json

    datos = json.loads(homologacion.EJEMPLO.read_text(encoding="utf-8"))
    datos["es_ejemplo"] = False
    copia = tmp_path / "copia.json"
    copia.write_text(json.dumps(datos, indent=4), encoding="utf-8")
    assert homologacion.cargar(copia).es_ejemplo is True

    datos["estado_escribano"]["NUEVO"] = "ACTIVO"
    propia = tmp_path / "propia.json"
    propia.write_text(json.dumps(datos), encoding="utf-8")
    tabla = homologacion.cargar(propia)
    assert tabla.es_ejemplo is False
    assert tabla.huella != homologacion.cargar().huella
