"""Actos de las DDJJ del sistema anterior (`actos.csv`, opcional en el v2).

El sistema anterior guarda cada acto declarado con su protocolo, escritura, naturaleza, base y
aporte repartido por cargo. Se migran tal cual a `historico_actos` (solo lectura) para la consulta
«por acto» del Anexo I; cuadran en filas y aporte total, pero no tocan los saldos.
"""

import csv
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.iam.models import User
from app.modules.migracion import carga, formato, homologacion, service
from app.modules.migracion.catalog import Entidad, ModoCorrida, Severidad
from app.modules.migracion.formato import COLUMNAS
from app.modules.migracion.models import HistoricoActo
from app.modules.migracion.validacion import CERO, Existentes, Staging, validar
from app.modules.padron.models import Escribano
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.reportes.test_reportes import verificar_paridad

Maker = async_sessionmaker[AsyncSession]


def _leer(directorio: Path, archivo: str) -> list[dict[str, str]]:
    with (directorio / archivo).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _escribir_actos(directorio: Path, filas: list[dict[str, str]]) -> None:
    """Reemplaza actos.csv y su fila de control (como lo declararía el origen)."""
    obligatorias, opcionales = COLUMNAS[Entidad.ACTOS]
    with (directorio / "actos.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*obligatorias, *opcionales], delimiter=";")
        writer.writeheader()
        writer.writerows(filas)
    total = sum((Decimal(f["importe"].replace(",", ".")) for f in filas), Decimal(0))
    control = [f for f in _leer(directorio, "control.csv") if f["entidad"] != "actos"]
    control.append({"entidad": "actos", "filas": str(len(filas)), "importe": f"{total:.2f}"})
    with (directorio / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)


def _validar(directorio: Path) -> Staging:
    return validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())


def _observaciones(st: Staging) -> set[tuple[str, str, Severidad]]:
    return {
        (o.codigo_legado, o.codigo, o.severidad)
        for o in st.observaciones
        if o.entidad is Entidad.ACTOS
    }


# --------------------------------------------------------------------------- formato y validación


def test_el_archivo_es_opcional(lote: Callable[..., Path]) -> None:
    sin = formato.leer_lote(lote("sin", actos=False))
    assert Entidad.ACTOS not in sin.presentes
    assert "actos" not in sin.control
    assert _validar(lote("sin2", actos=False)).actos == []
    assert Entidad.ACTOS in formato.leer_lote(lote("con")).presentes


def test_actos_validos_se_normalizan(lote: Callable[..., Path]) -> None:
    directorio = lote()
    filas = _leer(directorio, "actos.csv")
    st = _validar(directorio)
    assert st.observaciones == []
    assert len(st.actos) == len(filas) > 1
    venta = next(a for a in st.actos if a.base_imponible is not None)
    assert venta.tipo_protocolo == "GENERAL"
    assert venta.cargo == "TITULAR"
    assert venta.escribano is not None
    assert venta.aporte_variable == venta.importe == venta.aporte_titular
    assert venta.aporte_fijo is None
    assert venta.fecha_acto is not None and venta.periodo == f"{venta.fecha_acto:%Y-%m}"
    poder = next(a for a in st.actos if a.aporte_fijo is not None)
    assert poder.tipo_protocolo == "AUXILIAR"
    assert poder.base_imponible is None
    assert st.importe_leido["actos"] == sum((a.importe for a in st.actos), CERO)


def test_defectos_del_lote_sintetico(lote: Callable[..., Path]) -> None:
    st = _validar(lote(defectos=True))
    obs = _observaciones(st)
    # El reparto por cargo tiene que cerrar con el total: el acto no se carga.
    assert ("ACT-700-202609-0", "REPARTO_NO_CUADRA", Severidad.BLOQUEANTE) in obs
    # El registro rechazado arrastra a sus actos.
    assert ("ACT-REGISTRO-RECHAZADO", "REGISTRO_NO_MIGRADO", Severidad.BLOQUEANTE) in obs
    # Un escribano que no se carga no bloquea el acto: queda el dato del origen.
    assert ("ACT-ESCRIBANO-DESCONOCIDO", "ESCRIBANO_A_COMPLETAR", Severidad.ADVERTENCIA) in obs
    cargados = {a.codigo: a for a in st.actos}
    assert {"ACT-700-202609-0", "ACT-REGISTRO-RECHAZADO"}.isdisjoint(cargados)
    desconocido = cargados["ACT-ESCRIBANO-DESCONOCIDO"]
    assert desconocido.escribano is None
    assert desconocido.escribano_origen == "ESC-NO-MIGRADO"
    assert st.leidas["actos"] == len(st.actos) + st.rechazadas["actos"]


def test_reglas_de_cada_acto(lote: Callable[..., Path]) -> None:
    directorio = lote()
    base = _leer(directorio, "actos.csv")[0]
    casos = {
        # Variable + fijo distinto del total.
        "ACT-NO-CUADRA": {"aporte_variable": "10,00", "importe": "11,00", "aporte_titular": ""},
        "ACT-PROTOCOLO": {"tipo_protocolo": "NOTARIAL"},
        "ACT-NEGATIVO": {"base_imponible": "-5,00"},
        "ACT-EXENTO": {"exento": "quizás"},
        # Advertencias: la fila se carga igual.
        "ACT-FUERA": {"fecha_acto": "2026-01-05"},
        "ACT-EXENTO-CON-APORTE": {"exento": "SI"},
        "ACT-A-CARGO": {"cargo": "A Cargo", "escribano": "", "escribano_origen": "20123456786"},
        # El escribano no tenía cargo en ese registro: no se le vincula el acto.
        "ACT-SIN-CARGO": {"numero_registro": "701", "numero_escritura": "999"},
    }
    filas = [{**base, "codigo_legado": codigo, **cambios} for codigo, cambios in casos.items()]
    # La misma escritura del protocolo en otro mes del mismo año.
    filas.append({**base, "codigo_legado": "ACT-OTRO-MES", "periodo": "08/2026", "fecha_acto": ""})
    _escribir_actos(directorio, filas)
    st = _validar(directorio)
    obs = _observaciones(st)
    bloqueantes = {(c, o) for c, o, s in obs if s is Severidad.BLOQUEANTE}
    assert bloqueantes == {
        ("ACT-NO-CUADRA", "APORTE_NO_CUADRA"),
        ("ACT-PROTOCOLO", "VALOR_INVALIDO"),
        ("ACT-NEGATIVO", "IMPORTE_NEGATIVO"),
        ("ACT-EXENTO", "VALOR_INVALIDO"),
    }
    advertencias = {(c, o) for c, o, s in obs if s is Severidad.ADVERTENCIA}
    assert ("ACT-FUERA", "FECHA_FUERA_DEL_PERIODO") in advertencias
    assert ("ACT-EXENTO-CON-APORTE", "EXENTO_CON_APORTE") in advertencias
    assert ("ACT-A-CARGO", "ESCRIBANO_A_COMPLETAR") in advertencias
    assert ("ACT-OTRO-MES", "ESCRITURA_EN_OTRO_PERIODO") in advertencias
    assert ("ACT-SIN-CARGO", "ESCRIBANO_SIN_CARGO") in advertencias
    cargados = {a.codigo: a for a in st.actos}
    assert cargados["ACT-SIN-CARGO"].escribano is None
    assert cargados["ACT-SIN-CARGO"].escribano_origen == base["escribano"]
    assert cargados["ACT-A-CARGO"].cargo == "SUPLENTE_INTERINO"
    assert cargados["ACT-EXENTO-CON-APORTE"].exento is True
    assert {"ACT-NO-CUADRA", "ACT-PROTOCOLO", "ACT-NEGATIVO", "ACT-EXENTO"}.isdisjoint(cargados)


# --------------------------------------------------------------------------- carga y cuadratura


async def test_simulacro_con_actos_cuadra_sin_tocar_saldos(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    directorio = lote()
    st = _validar(directorio)
    con = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    assert con.cuadra is True, con.informe
    actos = next(e for e in con.informe["entidades"] if e["entidad"] == "actos")
    total = f"{sum((a.importe for a in st.actos), CERO):.2f}"
    assert actos["control_importe"] == actos["importe_leido"] == actos["importe_cargado"] == total
    assert actos["control_filas"] == actos["leidas"] == actos["cargadas"] == len(st.actos)

    sin = await service.correr(
        lote("sin", actos=False), ModoCorrida.SIMULACRO, operador.email, maker=maker
    )
    assert "actos" not in {e["entidad"] for e in sin.informe["entidades"]}
    # Los actos son el detalle declarado: los saldos salen de boletas, pagos y créditos.
    assert con.informe["saldos"] == sin.informe["saldos"]


async def test_lo_cargado_es_lo_declarado(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)
    filas = (
        await db_session.scalars(
            select(HistoricoActo).where(HistoricoActo.corrida_id == r.corrida_id)
        )
    ).all()
    assert {(a.codigo_legado, a.importe, a.naturaleza) for a in filas} == {
        (a.codigo, a.importe, a.naturaleza) for a in st.actos
    }
    assert all(a.escribano_id is not None for a in filas)
    primero = filas[0]
    assert cargado.ids[Entidad.ACTOS][primero.codigo_legado] == primero.id
    escribano = next(a.escribano for a in st.actos if a.codigo == primero.codigo_legado)
    assert escribano is not None
    assert cargado.ids[Entidad.ESCRIBANOS][escribano] == primero.escribano_id


@pytest.mark.parametrize(
    "sentencia",
    [
        "UPDATE historico_actos SET importe = importe + 1",
        "DELETE FROM historico_actos",
        "TRUNCATE historico_actos",
        "INSERT INTO historico_actos (id, corrida_id, codigo_legado, registro_id, periodo, "
        "numero_escritura, naturaleza, importe) SELECT gen_random_uuid(), corrida_id, "
        "'X-' || codigo_legado, registro_id, periodo, numero_escritura, naturaleza, 1 "
        "FROM historico_actos LIMIT 1",
    ],
)
async def test_historico_de_actos_inmutable(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    sentencia: str,
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)
    await db_session.execute(text("SET LOCAL suite.migracion = 'off'"))
    with pytest.raises(DBAPIError, match=r"no se modifica|no se borra|solo se carga|permission"):
        async with db_session.begin_nested():
            await db_session.execute(text(sentencia))


# --------------------------------------------------------------------------- reportes


async def test_reportes_de_actos_historicos(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    auditor: AsyncClient,
    client: AsyncClient,
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)

    pantalla = await auditor.get("/api/v1/reportes/ACTOS_HISTORICOS", params={"page_size": 100})
    assert pantalla.status_code == 200, pantalla.text
    body = pantalla.json()
    assert body["total"] == len(st.actos)
    assert Decimal(body["totales"]["aporte"]) == sum((a.importe for a in st.actos), CERO)
    await verificar_paridad(auditor, "ACTOS_HISTORICOS", {})
    filtros = {"registro": "701", "protocolo": "GENERAL", "naturaleza": "compra"}
    filtrado = (await auditor.get("/api/v1/reportes/ACTOS_HISTORICOS", params=filtros)).json()
    assert filtrado["total"] == sum(
        1 for a in st.actos if a.numero_registro == 701 and a.tipo_protocolo == "GENERAL"
    )
    await verificar_paridad(auditor, "ACTOS_HISTORICOS", filtros)

    # El escribano ve los actos de los registros donde tenía el cargo, nada más.
    titular = next(a.escribano for a in st.actos if a.numero_registro == 701)
    assert titular is not None
    usuario = await make_user(db_session)
    await db_session.execute(
        update(Escribano)
        .where(Escribano.id == cargado.ids[Entidad.ESCRIBANOS][titular])
        .values(user_id=usuario.id)
    )
    await login(client, usuario)
    assert (await client.get("/api/v1/reportes/ACTOS_HISTORICOS")).status_code == 403
    mios = (await client.get("/api/v1/reportes/MIS_ACTOS_HISTORICOS")).json()
    assert mios["total"] == sum(1 for a in st.actos if a.numero_registro == 701) > 0
    assert {f["registro"] for f in mios["items"]} == {701}
    await verificar_paridad(client, "MIS_ACTOS_HISTORICOS", {})
