"""Formato v2: licencias, primera escritura, circunscripción por defecto y domicilios.

`licencias.csv` es opcional; si viene, cuadra como los demás archivos. Una licencia de un
escribano que no se carga cae en cascada. La matrícula no es única: se migra repetida.
"""

import csv
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.iam.models import User
from app.modules.migracion import carga, formato, homologacion, service
from app.modules.migracion.catalog import Entidad, ModoCorrida, Severidad
from app.modules.migracion.formato import CIRCUNSCRIPCION_POR_DEFECTO, FormatoInvalidoError
from app.modules.migracion.validacion import MOTIVO_LICENCIA_MIGRADA, Existentes, Staging, validar
from app.modules.padron.models import (
    Circunscripcion,
    DomicilioRegistro,
    Escribano,
    Licencia,
    RegistroNotarial,
)

Maker = async_sessionmaker[AsyncSession]
CORRIDA = date(2026, 10, 1)


def _leer(directorio: Path, archivo: str) -> list[dict[str, str]]:
    with (directorio / archivo).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _reescribir(directorio: Path, entidad: Entidad, filas: list[dict[str, str]]) -> None:
    """Reemplaza el archivo de la entidad y su fila de control (como lo declararía el origen)."""
    obligatorias, opcionales = formato.COLUMNAS[entidad]
    with (directorio / f"{entidad.value}.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*obligatorias, *opcionales], delimiter=";")
        writer.writeheader()
        writer.writerows(filas)
    control = [c for c in _leer(directorio, "control.csv") if c["entidad"] != entidad.value]
    control.append({"entidad": entidad.value, "filas": str(len(filas)), "importe": ""})
    with (directorio / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)


def _validar(directorio: Path) -> Staging:
    return validar(
        formato.leer_lote(directorio), homologacion.cargar(), Existentes(), fecha_corrida=CORRIDA
    )


def _observaciones(st: Staging) -> set[tuple[str, str, Severidad]]:
    return {(o.codigo_legado, o.codigo, o.severidad) for o in st.observaciones}


# --------------------------------------------------------------------------- formato


def test_licencias_es_opcional_y_exige_su_control(lote: Callable[..., Path]) -> None:
    sin = formato.leer_lote(lote("sin", licencias=False))
    assert Entidad.LICENCIAS not in sin.presentes and sin.filas[Entidad.LICENCIAS] == []
    con = formato.leer_lote(lote("con"))
    assert Entidad.LICENCIAS in con.presentes and con.filas[Entidad.LICENCIAS]

    sin_control = lote("sin_control")
    control = [c for c in _leer(sin_control, "control.csv") if c["entidad"] != "licencias"]
    with (sin_control / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)
    with pytest.raises(FormatoInvalidoError, match="faltan los totales de licencias"):
        formato.leer_lote(sin_control)

    sin_archivo = lote("sin_archivo")
    (sin_archivo / "licencias.csv").unlink()
    with pytest.raises(FormatoInvalidoError, match="no trae el archivo"):
        formato.leer_lote(sin_archivo)


def test_circunscripcion_opcional_y_por_defecto(lote: Callable[..., Path]) -> None:
    directorio = lote()
    registros = _leer(directorio, "registros.csv")
    registros[0]["circunscripcion"] = ""
    _reescribir(directorio, Entidad.REGISTROS, registros)
    st = _validar(directorio)
    assert st.registros[0].circunscripcion == CIRCUNSCRIPCION_POR_DEFECTO == "San Juan"
    assert not [o for o in st.observaciones if o.entidad is Entidad.REGISTROS]

    # Sin la columna, también.
    for fila in registros:
        del fila["circunscripcion"]
    with (directorio / "registros.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(registros[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(registros)
    st = _validar(directorio)
    assert {r.circunscripcion for r in st.registros} == {"San Juan"}


# --------------------------------------------------------------------------- validación


def test_licencias_validadas_con_cascada(lote: Callable[..., Path]) -> None:
    directorio = lote()
    escribanos = _leer(directorio, "escribanos.csv")
    vivo = escribanos[5]
    escribanos.append(
        {
            **{k: "" for k in escribanos[0]},
            "codigo_legado": "ESC-FALLECIDO",
            "apellido": "Ficticio",
            "nombre": "Ana",
            "estado": "F",
            "fecha_matriculacion": "01/03/2001",
        }
    )
    _reescribir(directorio, Entidad.ESCRIBANOS, escribanos)
    licencias = [
        {
            "codigo_legado": "LIC-OK",
            "escribano": vivo["codigo_legado"],
            "fecha_desde": "01/02/2022",
            "fecha_hasta": "",
            "motivo": "",
        },
        {
            "codigo_legado": "LIC-SIN-ESCRIBANO",
            "escribano": "ESC-QUE-NO-EXISTE",
            "fecha_desde": "01/02/2022",
            "fecha_hasta": "",
            "motivo": "",
        },
        {
            "codigo_legado": "LIC-INVERTIDA",
            "escribano": vivo["codigo_legado"],
            "fecha_desde": "01/02/2020",
            "fecha_hasta": "01/01/2020",
            "motivo": "Viaje",
        },
        {
            "codigo_legado": "LIC-FALLECIDO",
            "escribano": "ESC-FALLECIDO",
            "fecha_desde": "01/02/2010",
            "fecha_hasta": "",
            "motivo": "",
        },
        {
            "codigo_legado": "LIC-FALLECIDO-PASADA",
            "escribano": "ESC-FALLECIDO",
            "fecha_desde": "01/02/1999",
            "fecha_hasta": "01/06/1999",
            "motivo": "Estudios",
        },
        {
            "codigo_legado": "",
            "escribano": vivo["codigo_legado"],
            "fecha_desde": "",
            "fecha_hasta": "",
            "motivo": "",
        },
    ]
    _reescribir(directorio, Entidad.LICENCIAS, licencias)

    st = _validar(directorio)

    obs = _observaciones(st)
    assert ("LIC-SIN-ESCRIBANO", "ESCRIBANO_NO_MIGRADO", Severidad.BLOQUEANTE) in obs
    assert ("LIC-INVERTIDA", "FECHAS_INVERTIDAS", Severidad.BLOQUEANTE) in obs
    assert ("LIC-FALLECIDO", "LICENCIA_VIGENTE_SIN_EJERCICIO", Severidad.BLOQUEANTE) in obs
    assert (
        "LIC-FALLECIDO-PASADA",
        "LICENCIA_ANTERIOR_AL_JURAMENTO",
        Severidad.ADVERTENCIA,
    ) in obs
    assert ("", "DATO_FALTANTE", Severidad.BLOQUEANTE) in obs
    cargadas = {lic.codigo: lic for lic in st.licencias}
    assert set(cargadas) == {"LIC-OK", "LIC-FALLECIDO-PASADA"}
    assert cargadas["LIC-OK"].motivo == MOTIVO_LICENCIA_MIGRADA
    assert cargadas["LIC-FALLECIDO-PASADA"].motivo == "Estudios"
    assert (
        st.leidas["licencias"] == len(licencias) == len(st.licencias) + st.rechazadas["licencias"]
    )


def test_primera_escritura_invalida_no_rechaza_al_escribano(lote: Callable[..., Path]) -> None:
    directorio = lote(licencias=False)
    escribanos = _leer(directorio, "escribanos.csv")
    incompleta, mala, anterior, buena = escribanos[3], escribanos[4], escribanos[6], escribanos[7]
    incompleta |= {"primera_escritura_fecha": "10/05/2021", "primera_escritura_numero": "3"}
    mala |= {
        "primera_escritura_fecha": "31/02/2021",
        "primera_escritura_numero": "3",
        "primera_escritura_registro": "12",
    }
    anterior |= {
        "fecha_matriculacion": "01/03/2010",
        "primera_escritura_fecha": "01/01/2009",
        "primera_escritura_numero": "1",
        "primera_escritura_registro": "12",
    }
    buena |= {
        "primera_escritura_fecha": "10/05/2021",
        "primera_escritura_numero": "A-77",
        "primera_escritura_registro": "4",
        "primera_escritura_folio": "220",
    }
    _reescribir(directorio, Entidad.ESCRIBANOS, escribanos)

    st = _validar(directorio)

    obs = _observaciones(st)
    for fila in (incompleta, mala):
        assert (
            fila["codigo_legado"],
            "PRIMERA_ESCRITURA_NO_MIGRADA",
            Severidad.ADVERTENCIA,
        ) in obs
    assert (
        anterior["codigo_legado"],
        "PRIMERA_ESCRITURA_ANTERIOR_AL_JURAMENTO",
        Severidad.ADVERTENCIA,
    ) in obs
    por_codigo = {e.codigo: e for e in st.escribanos}
    assert len(por_codigo) == len(escribanos)  # nadie queda afuera
    assert por_codigo[incompleta["codigo_legado"]].primera_escritura_fecha is None
    assert por_codigo[mala["codigo_legado"]].primera_escritura_numero is None
    b = por_codigo[buena["codigo_legado"]]
    assert (b.primera_escritura_fecha, b.primera_escritura_numero) == (date(2021, 5, 10), "A-77")
    assert (b.primera_escritura_registro, b.primera_escritura_folio) == (4, "220")


def test_matricula_repetida_se_migra(lote: Callable[..., Path]) -> None:
    directorio = lote()
    escribanos = _leer(directorio, "escribanos.csv")
    escribanos[6]["matricula"] = escribanos[5]["matricula"]
    _reescribir(directorio, Entidad.ESCRIBANOS, escribanos)
    st = _validar(directorio)
    assert st.bloqueantes() == 0
    matriculas = [e.matricula for e in st.escribanos if e.matricula is not None]
    assert len(matriculas) > len(set(matriculas))


# --------------------------------------------------------------------------- carga


async def test_simulacro_con_licencias_cuadra(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    directorio = lote()
    st = _validar(directorio)
    assert st.licencias
    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    assert r.cuadra is True, r.informe
    licencias = next(e for e in r.informe["entidades"] if e["entidad"] == "licencias")
    assert licencias["control_filas"] == licencias["leidas"] == licencias["cargadas"]
    assert licencias["cargadas"] == len(st.licencias)


async def test_lote_sin_licencias_no_las_informa(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    r = await service.correr(
        lote(licencias=False), ModoCorrida.SIMULACRO, operador.email, maker=maker
    )
    assert r.cuadra is True
    assert "licencias" not in {e["entidad"] for e in r.informe["entidades"]}


async def test_carga_licencias_primera_escritura_domicilios_y_circunscripcion(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    directorio = lote()
    registros = _leer(directorio, "registros.csv")
    registros[0]["circunscripcion"] = ""
    registros[0]["fecha_creacion"] = "02/05/1990"
    _reescribir(directorio, Entidad.REGISTROS, registros)
    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(directorio)
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)

    # Licencias, con su escribano y el motivo por defecto si el origen no lo trae.
    ids = list(cargado.ids[Entidad.LICENCIAS].values())
    filas = (await db_session.scalars(select(Licencia).where(Licencia.id.in_(ids)))).all()
    assert len(filas) == len(st.licencias) > 0
    esperado = {
        (cargado.ids[Entidad.ESCRIBANOS][lic.escribano], lic.desde, lic.hasta)
        for lic in st.licencias
    }
    assert {(f.escribano_id, f.fecha_desde, f.fecha_hasta) for f in filas} == esperado
    assert all(f.motivo and not f.anulada for f in filas)
    assert any(f.fecha_hasta is None for f in filas)  # una vigente

    # Primera escritura, con quién la cargó.
    con_primera = [e for e in st.escribanos if e.primera_escritura_fecha is not None]
    assert con_primera
    for e in con_primera:
        escribano = await db_session.get(Escribano, cargado.ids[Entidad.ESCRIBANOS][e.codigo])
        assert escribano is not None
        assert escribano.primera_escritura_numero == e.primera_escritura_numero
        assert escribano.primera_escritura_cargada_por_user_id == operador.id

    # Un domicilio vigente por registro: desde su creación o desde el día de la corrida.
    registro_ids = list(cargado.ids[Entidad.REGISTROS].values())
    domicilios = (
        await db_session.scalars(
            select(DomicilioRegistro).where(DomicilioRegistro.registro_id.in_(registro_ids))
        )
    ).all()
    assert len(domicilios) == len(registro_ids)
    assert all(d.fecha_hasta is None for d in domicilios)
    primero = cargado.ids[Entidad.REGISTROS][st.registros[0].codigo]
    assert next(d for d in domicilios if d.registro_id == primero).fecha_desde == date(1990, 5, 2)
    assert {d.fecha_desde for d in domicilios if d.registro_id != primero} == {CORRIDA}

    # La circunscripción vacía va a «San Juan».
    registro = await db_session.get(RegistroNotarial, primero)
    assert registro is not None
    circ = await db_session.get(Circunscripcion, registro.circunscripcion_id)
    assert circ is not None and circ.nombre == "San Juan"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Licencia).where(Licencia.id.in_(ids))
        )
    ) == len(st.licencias)
