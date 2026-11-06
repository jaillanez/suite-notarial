"""Formato de intercambio v2: datos «a completar» y cargos referenciados por código del origen."""

import csv
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import User
from app.modules.migracion import carga, formato, homologacion
from app.modules.migracion.catalog import Entidad, Severidad
from app.modules.migracion.validacion import Existentes, Staging, validar
from app.modules.padron.models import Adscripcion, Escribano, Persona
from tests.migracion.test_corridas import Maker, _simulacro


def _editar(directorio: Path, entidad: Entidad, cambios: dict[int, dict[str, str]]) -> None:
    """Cambia columnas de algunas filas (índice 0 = primera fila de datos)."""
    archivo = directorio / f"{entidad.value}.csv"
    with archivo.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        columnas = list(lector.fieldnames or [])
        filas = list(lector)
    for indice, valores in cambios.items():
        filas[indice].update(valores)
    with archivo.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _agregar_cargo(directorio: Path, fila: dict[str, str]) -> None:
    with (directorio / "cargos.csv").open("a", encoding="utf-8", newline="") as f:
        obligatorias, opcionales = formato.COLUMNAS[Entidad.CARGOS]
        csv.DictWriter(f, fieldnames=[*obligatorias, *opcionales], delimiter=";").writerow(fila)


def _validar(directorio: Path) -> Staging:
    return validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())


SIN_IDENTIDAD = {"cuit": "", "numero_documento": "", "matricula": "", "fecha_matriculacion": ""}


def test_version_del_formato() -> None:
    assert formato.VERSION_FORMATO == "2"
    _, opcionales = formato.COLUMNAS[Entidad.ESCRIBANOS]
    assert {"cuit", "numero_documento", "matricula", "fecha_matriculacion"} <= set(opcionales)
    assert "escribano" in formato.COLUMNAS[Entidad.CARGOS][0]
    assert "matricula" not in formato.COLUMNAS[Entidad.CARGOS][0]


def test_lote_v1_se_rechaza_con_un_mensaje_claro(lote: Callable[..., Path]) -> None:
    directorio = lote()
    archivo = directorio / "cargos.csv"
    texto = archivo.read_text(encoding="utf-8")
    archivo.write_text(texto.replace("escribano;", "matricula;", 1), encoding="utf-8")
    with pytest.raises(formato.FormatoInvalidoError, match="formato v1"):
        formato.leer_lote(directorio)


def test_escribanos_sin_datos_se_validan_sin_observaciones(lote: Callable[..., Path]) -> None:
    directorio = lote()
    _editar(directorio, Entidad.ESCRIBANOS, {0: SIN_IDENTIDAD, 1: SIN_IDENTIDAD})
    st = _validar(directorio)
    assert st.bloqueantes() == 0
    # Sin CUIT no hay advertencia de DNI distinto del CUIT ni duplicados por vacío.
    assert st.observaciones == []
    sin = [e for e in st.escribanos if e.cuit is None]
    assert len(sin) >= 2
    assert all(e.matricula is None and e.numero_documento is None for e in sin[:2])
    assert all(e.fecha_matriculacion is None for e in sin[:2])


def test_matricula_presente_sigue_validandose(lote: Callable[..., Path]) -> None:
    directorio = lote()
    _editar(directorio, Entidad.ESCRIBANOS, {0: {"matricula": "0"}, 1: {"matricula": "abc"}})
    st = _validar(directorio)
    codigos = [o.codigo for o in st.observaciones if o.severidad is Severidad.BLOQUEANTE]
    assert codigos.count("VALOR_INVALIDO") == 2


def test_cuit_presente_sigue_validandose(lote: Callable[..., Path]) -> None:
    directorio = lote()
    leido = formato.leer_lote(directorio)
    cuit = leido.filas[Entidad.ESCRIBANOS][0].datos["cuit"]
    _editar(directorio, Entidad.ESCRIBANOS, {1: {"cuit": cuit}})
    st = _validar(directorio)
    assert sum(o.codigo == "CUIT_DUPLICADO" for o in st.observaciones) == 2


def test_cargo_de_escribano_inexistente_o_rechazado_no_se_carga(
    lote: Callable[..., Path],
) -> None:
    directorio = lote()
    # El escribano de la fila 0 queda rechazado (sin apellido); su cargo cae en cascada.
    _editar(directorio, Entidad.ESCRIBANOS, {0: {"apellido": ""}})
    rechazado = formato.leer_lote(directorio).filas[Entidad.ESCRIBANOS][0].codigo
    _agregar_cargo(
        directorio,
        {
            "codigo_legado": "CAR-FANTASMA",
            "escribano": "ESC-NO-EXISTE",
            "numero_registro": formato.leer_lote(directorio)
            .filas[Entidad.REGISTROS][0]
            .datos["numero_registro"],
            "cargo": "A",
            "fecha_desde": "01/01/2015",
            "fecha_hasta": "31/12/2015",
        },
    )
    st = _validar(directorio)
    no_migrados = {o.codigo_legado for o in st.observaciones if o.codigo == "ESCRIBANO_NO_MIGRADO"}
    assert "CAR-FANTASMA" in no_migrados
    assert all(c.escribano != rechazado for c in st.cargos)
    assert all(c.codigo != "CAR-FANTASMA" for c in st.cargos)
    assert len(no_migrados) == 2


def test_cargos_vigentes_multiples_por_codigo_de_escribano(lote: Callable[..., Path]) -> None:
    directorio = lote()
    leido = formato.leer_lote(directorio)
    # Un escribano sin matrícula con dos cargos vigentes: se detecta por su código.
    _editar(directorio, Entidad.ESCRIBANOS, {0: SIN_IDENTIDAD})
    codigo = leido.filas[Entidad.ESCRIBANOS][0].codigo
    _agregar_cargo(
        directorio,
        {
            "codigo_legado": "CAR-DOBLE",
            "escribano": codigo,
            "numero_registro": leido.filas[Entidad.REGISTROS][-1].datos["numero_registro"],
            "cargo": "A",
            "fecha_desde": "01/01/2016",
            "fecha_hasta": "",
        },
    )
    st = _validar(directorio)
    assert sum(o.codigo == "CARGOS_VIGENTES_MULTIPLES" for o in st.observaciones) == 2


async def test_carga_escribanos_sin_datos_como_null(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
) -> None:
    directorio = lote()
    _editar(directorio, Entidad.ESCRIBANOS, {0: SIN_IDENTIDAD, 1: SIN_IDENTIDAD})
    r = await _simulacro(maker, directorio, operador)
    assert r.bloqueantes == 0 and r.cuadra is True

    st = _validar(directorio)
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)
    leido = formato.leer_lote(directorio)
    codigos = [leido.filas[Entidad.ESCRIBANOS][i].codigo for i in (0, 1)]
    ids = [cargado.ids[Entidad.ESCRIBANOS][c] for c in codigos]
    escribanos = list(
        (await db_session.scalars(select(Escribano).where(Escribano.id.in_(ids)))).unique()
    )
    # Dos escribanos sin matrícula ni CUIT conviven: UNIQUE admite varios NULL.
    assert len(escribanos) == 2
    for e in escribanos:
        assert e.matricula_numero is None and e.fecha_matriculacion is None
        persona = await db_session.get(Persona, e.persona_id)
        assert persona is not None
        assert persona.cuit is None and persona.numero_documento is None
        # Su cargo se cargó referenciado por el código del origen.
        cargo = await db_session.scalar(select(Adscripcion).where(Adscripcion.escribano_id == e.id))
        assert cargo is not None
