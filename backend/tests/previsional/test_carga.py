"""Carga de la planilla: idempotencia, diferencias sin sobreescribir, vínculo con el padrón,
inmutabilidad en la base y la consola (con planillas sintéticas)."""

import argparse
import csv
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common.audit import AuditSecurityLog, RequestContext
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.iam.models import User
from app.modules.previsional import cargar_puntos, service
from app.modules.previsional.catalog import EstadoVinculo, Vinculacion
from app.modules.previsional.models import Ejercicio, PuntosAfiliado
from app.modules.previsional.planilla import leer_planilla
from tests.iam.factories import make_user
from tests.previsional.conftest import Hoja, crear_escribano, escribir_xlsx

CTX = RequestContext(ip_address=None, user_agent="test", correlation_id=None)


async def _puntos(session: AsyncSession) -> list[PuntosAfiliado]:
    return list(
        (
            await session.scalars(
                select(PuntosAfiliado).order_by(PuntosAfiliado.nombre_origen, PuntosAfiliado.puntos)
            )
        ).all()
    )


async def test_carga_vincula_e_idempotente(
    db_session: AsyncSession, operador: User, planilla_xlsx: Callable[..., Path]
) -> None:
    ana = await crear_escribano(db_session, "Prueba", "Ana Sintética")
    luis = await crear_escribano(db_session, "Ejemplo Gómez", "Luis Alberto")
    planilla = leer_planilla(planilla_xlsx())

    r = await service.cargar(db_session, planilla, operador, "Planilla sintética", CTX)
    await db_session.commit()

    assert (r.ejercicios_nuevos, r.puntos_nuevos, r.diferencias) == (2, 4, [])
    assert r.vinculacion.exactas == 1
    assert r.vinculacion.aproximadas == [("EJEMPLO GÓMEZ Luis", luis.id)]
    assert r.vinculacion.sin_vincular == ["FICTICIO Pedro S."]
    filas = {(p.nombre_origen, p.puntos): p for p in await _puntos(db_session)}
    ana_90 = filas[("PRUEBA Ana Sintética", Decimal("97.639503"))]
    assert (ana_90.escribano_id, ana_90.vinculacion) == (ana.id, Vinculacion.EXACTA.value)
    # Un vínculo automático no se atribuye al operador de la carga.
    assert ana_90.vinculado_por_user_id is None
    assert ana_90.aportes == Decimal("82466.67") and ana_90.fila_origen == 6
    # La coincidencia aproximada es solo una sugerencia: los puntos no son de nadie todavía.
    luis_90 = filas[("EJEMPLO GÓMEZ Luis", Decimal("102.360497"))]
    assert (luis_90.escribano_id, luis_90.vinculacion) == (None, None)
    assert luis_90.escribano_sugerido_id == luis.id
    assert filas[("FICTICIO Pedro S.", Decimal("150.000000"))].escribano_id is None
    ej = await db_session.scalar(select(Ejercicio).where(Ejercicio.anio == 1990))
    assert ej is not None and ej.total_aportes == Decimal("83466.67")
    assert ej.origen == "Planilla sintética" and ej.created_by_user_id == operador.id
    log = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PUNTOS_PLANILLA_CARGADA")
    )
    assert log is not None and log.details is not None
    assert log.details["puntos_nuevos"] == 4 and log.details["redondeos"] == 2
    # Ningún nombre de afiliado queda en la auditoría de la carga.
    assert "Ana" not in str(log.details)

    # Segunda corrida: nada nuevo, nada cambia.
    r2 = await service.cargar(db_session, planilla, operador, "Planilla sintética", CTX)
    assert (r2.ejercicios_nuevos, r2.puntos_nuevos) == (0, 0)
    assert (r2.ejercicios_iguales, r2.puntos_iguales) == (2, 4)
    assert await db_session.scalar(select(func.count()).select_from(PuntosAfiliado)) == 4


async def test_diferencias_no_se_sobreescriben(
    db_session: AsyncSession, operador: User, tmp_path: Path
) -> None:
    hoja = Hoja(anios=[2020], afiliados=[("UNO Prueba", [(10, 1)])], totales=[10])
    await service.cargar(
        db_session, leer_planilla(escribir_xlsx(hoja, tmp_path / "a.xlsx")), operador, "A", CTX
    )
    cambiada = Hoja(anios=[2020], afiliados=[("UNO Prueba", [(11, 1)])], totales=[11])

    r = await service.cargar(
        db_session, leer_planilla(escribir_xlsx(cambiada, tmp_path / "b.xlsx")), operador, "B", CTX
    )

    assert [(d.anio, d.fila, d.campos) for d in r.diferencias] == [
        (2020, None, {"total_aportes": ("10.00", "11.00")}),
        (2020, 6, {"aportes": ("10.00", "11.00")}),
    ]
    (fila,) = await _puntos(db_session)
    assert fila.aportes == Decimal("10.00") and fila.origen == "A"


async def test_revincular_despues_de_cargar_el_padron(
    db_session: AsyncSession, operador: User, planilla_xlsx: Callable[..., Path]
) -> None:
    await service.cargar(db_session, leer_planilla(planilla_xlsx()), operador, "P", CTX)
    assert all(p.escribano_id is None for p in await _puntos(db_session))

    ana = await crear_escribano(db_session, "Prueba", "Ana Sintética")
    pedro = await crear_escribano(db_session, "Ficticio", "Pedro Santos")
    r = await service.revincular_auditado(db_session, operador, CTX)

    assert r.exactas == 1 and r.aproximadas == [("FICTICIO Pedro S.", pedro.id)]
    assert r.sin_vincular == ["EJEMPLO GÓMEZ Luis"] and r.filas_vinculadas == 2
    vinculadas = {p.nombre_origen: p.escribano_id for p in await _puntos(db_session)}
    assert vinculadas["PRUEBA Ana Sintética"] == ana.id
    assert vinculadas["FICTICIO Pedro S."] is None
    log = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PUNTOS_REVINCULADOS")
    )
    assert log is not None and log.details == {
        "exactas": 1,
        "aproximadas": 1,
        "heredadas": 0,
        "ambiguas": 0,
        "sin_vincular": 1,
        "filas_vinculadas": 2,
    }

    # Rechazada la sugerencia, revincular no la vuelve a proponer.
    await service.rechazar_sugerencia(
        db_session, "FICTICIO Pedro S.", "No es la misma persona", operador, CTX
    )
    r2 = await service.revincular(db_session)
    assert r2.aproximadas == [] and "FICTICIO Pedro S." in r2.sin_vincular
    (fila,) = [p for p in await _puntos(db_session) if p.nombre_origen == "FICTICIO Pedro S."]
    assert (fila.escribano_sugerido_id, fila.sugerencia_rechazada_id) == (None, pedro.id)
    rechazo = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PUNTOS_SUGERENCIA_RECHAZADA")
    )
    assert rechazo is not None and rechazo.actor_user_id == operador.id
    with pytest.raises(ProblemError):
        await service.rechazar_sugerencia(
            db_session, "FICTICIO Pedro S.", "otra vez", operador, CTX
        )


async def test_ejercicio_nuevo_hereda_el_vinculo_manual(
    db_session: AsyncSession, operador: User, tmp_path: Path
) -> None:
    esc = await crear_escribano(db_session, "Nombre", "Muy Distinto")
    hoja = Hoja(anios=[2020], afiliados=[("ALIAS Planilla", [(10, 1)])], totales=[10])
    await service.cargar(
        db_session, leer_planilla(escribir_xlsx(hoja, tmp_path / "a.xlsx")), operador, "A", CTX
    )
    await service.vincular_manual(db_session, "ALIAS Planilla", esc.id, None, operador, CTX)
    otro = Hoja(anios=[2021], afiliados=[("ALIAS Planilla", [(20, 2)])], totales=[20])

    r = await service.cargar(
        db_session, leer_planilla(escribir_xlsx(otro, tmp_path / "b.xlsx")), operador, "B", CTX
    )

    assert r.vinculacion.heredadas == 1
    filas = {p.aportes: p for p in await _puntos(db_session)}
    # La decisión humana conserva su autor; la fila nueva cuenta para el mismo escribano pero
    # como HEREDADA, sin autor (no se atribuye al operador de esta carga).
    previa, nueva = filas[Decimal("10.00")], filas[Decimal("20.00")]
    assert (previa.escribano_id, previa.vinculacion, previa.vinculado_por_user_id) == (
        esc.id,
        "MANUAL",
        operador.id,
    )
    assert (nueva.escribano_id, nueva.vinculacion, nueva.vinculado_por_user_id) == (
        esc.id,
        "HEREDADA",
        None,
    )
    # Cuenta en el informe del escribano y aparece en la cola para confirmarla.
    informe = await service.informe(db_session, esc)
    assert informe.total_puntos == Decimal("3.000000")
    cola, total = await service.sin_vincular(
        db_session, EstadoVinculo.HEREDADA, None, PageParams(page=1, page_size=10)
    )
    assert total == 1 and cola[0].ejercicios == 1 and cola[0].primer_anio == 2021
    # Confirmarla la convierte en MANUAL con autor y la saca de la cola.
    await service.vincular_manual(db_session, "ALIAS Planilla", esc.id, None, operador, CTX)
    operador_id = operador.id
    db_session.expire_all()
    assert {(p.vinculacion, p.vinculado_por_user_id) for p in await _puntos(db_session)} == {
        ("MANUAL", operador_id)
    }


async def test_herencia_de_un_vinculo_exacto_sigue_exacta(
    db_session: AsyncSession, operador: User, tmp_path: Path
) -> None:
    esc = await crear_escribano(db_session, "Uno", "Prueba")
    hoja = Hoja(anios=[2020], afiliados=[("UNO Prueba", [(10, 1)])], totales=[10])
    await service.cargar(
        db_session, leer_planilla(escribir_xlsx(hoja, tmp_path / "a.xlsx")), operador, "A", CTX
    )
    # El escribano cambia de nombre en el padrón: la fila nueva ya no coincide, pero hereda.
    await db_session.refresh(esc, attribute_names=["persona"])
    esc.persona.nombre = "Otro Nombre"
    await db_session.flush()
    otro = Hoja(anios=[2021], afiliados=[("UNO Prueba", [(20, 2)])], totales=[20])
    r = await service.cargar(
        db_session, leer_planilla(escribir_xlsx(otro, tmp_path / "b.xlsx")), operador, "B", CTX
    )
    assert r.vinculacion.heredadas == 1
    assert {(p.vinculacion, p.vinculado_por_user_id) for p in await _puntos(db_session)} == {
        ("EXACTA", None)
    }


async def test_mismo_nombre_vinculado_a_dos_personas_es_ambiguo(
    db_session: AsyncSession, operador: User, tmp_path: Path
) -> None:
    uno = await crear_escribano(db_session, "Uno", "Primero")
    dos = await crear_escribano(db_session, "Dos", "Segundo")
    hoja = Hoja(anios=[2019, 2020], afiliados=[("ALIAS X", [(1, 1), (2, 2)])], totales=[1, 2])
    await service.cargar(
        db_session, leer_planilla(escribir_xlsx(hoja, tmp_path / "a.xlsx")), operador, "A", CTX
    )
    # Dos filas del mismo nombre vinculadas a personas distintas (situación heredada).
    filas = await _puntos(db_session)
    for fila, esc in zip(filas, (uno, dos), strict=True):
        fila.escribano_id, fila.vinculacion, fila.vinculado_por_user_id = (
            esc.id,
            "MANUAL",
            operador.id,
        )
    await db_session.flush()
    nuevo = Hoja(anios=[2021], afiliados=[("ALIAS X", [(3, 3)])], totales=[3])

    r = await service.cargar(
        db_session, leer_planilla(escribir_xlsx(nuevo, tmp_path / "b.xlsx")), operador, "B", CTX
    )
    assert r.vinculacion.ambiguas == ["ALIAS X"]


async def test_la_base_impide_borrar_o_reescribir(
    db_session: AsyncSession, operador: User, planilla_xlsx: Callable[..., Path]
) -> None:
    await service.cargar(db_session, leer_planilla(planilla_xlsx()), operador, "P", CTX)
    await db_session.commit()
    for sql in (
        "UPDATE previsional_puntos SET aportes = aportes + 1",
        "UPDATE previsional_puntos SET origen = 'otro'",
        "UPDATE previsional_ejercicios SET total_aportes = 0",
        "DELETE FROM previsional_puntos",
        "DELETE FROM previsional_ejercicios",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(sql))
    # MANUAL siempre con autor; EXACTA y HEREDADA, nunca. Una sugerencia no convive con un
    # vínculo.
    esc_x = await crear_escribano(db_session, "Check", "Escribano")
    for sql in (
        "UPDATE previsional_puntos SET escribano_id = :e, vinculacion = 'MANUAL'",
        "UPDATE previsional_puntos SET escribano_id = :e, vinculacion = 'HEREDADA', "
        "vinculado_por_user_id = :u",
        "UPDATE previsional_puntos SET escribano_id = :e, vinculacion = 'EXACTA', "
        "escribano_sugerido_id = :e",
        "UPDATE previsional_puntos SET escribano_id = :e, vinculacion = 'APROXIMADA'",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(sql), {"e": esc_x.id, "u": operador.id})
    # El vínculo con el padrón sí puede cambiar (lo audita la aplicación).
    esc = await crear_escribano(db_session, "Otro", "Escribano")
    async with db_session.begin_nested():
        await db_session.execute(
            text(
                "UPDATE previsional_puntos SET escribano_id = :e, vinculacion = 'MANUAL', "
                "vinculado_por_user_id = :u WHERE escribano_id IS NULL"
            ),
            {"e": esc.id, "u": operador.id},
        )


async def test_operador_sin_permiso(db_session: AsyncSession) -> None:
    escribano_user = await make_user(db_session)
    with pytest.raises(service.CargaError, match="puntos:manage"):
        await service.operador(db_session, escribano_user.email)
    with pytest.raises(service.CargaError, match="No hay un usuario"):
        await service.operador(db_session, "nadie@suite-notarial.example")


# --------------------------------------------------------------------------- consola


@pytest.fixture
def consola(monkeypatch: pytest.MonkeyPatch, db_transaction: AsyncConnection) -> Callable[..., Any]:
    """La consola corre sobre la transacción del test (que se revierte al terminar)."""
    maker = async_sessionmaker(
        bind=db_transaction, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    monkeypatch.setattr(cargar_puntos, "get_sessionmaker", lambda: maker)

    class _Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(cargar_puntos, "get_engine", lambda: _Engine())

    async def correr(**kwargs: Any) -> int:
        defaults: dict[str, Any] = {
            "planilla": None,
            "operador": "",
            "simular": False,
            "revincular": False,
            "origen": None,
            "detalle": None,
        }
        return await cargar_puntos._correr(argparse.Namespace(**(defaults | kwargs)))

    return correr


async def test_consola_simular_no_guarda(
    consola: Callable[..., Any],
    operador: User,
    planilla_xlsx: Callable[..., Path],
    db_session: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await consola(planilla=planilla_xlsx(), operador=operador.email, simular=True) == 0

    salida = capsys.readouterr().out
    assert "Ejercicios leídos: 2 (1990 a 2025)" not in salida
    assert "Ejercicios leídos: 2 (1990 a 1991)" in salida
    assert "Afiliados leídos: 4" in salida
    assert "fila 6 · 1990 · aportes: 82466.667256 → 82466.67" in salida
    assert "SIMULACIÓN: no se guardó nada." in salida
    # La consola no muestra nombres de afiliados.
    assert "Ana" not in salida and "GÓMEZ" not in salida
    assert await db_session.scalar(select(func.count()).select_from(PuntosAfiliado)) == 0


async def test_consola_carga_con_detalle_y_revincula(
    consola: Callable[..., Any],
    operador: User,
    planilla_xlsx: Callable[..., Path],
    db_session: AsyncSession,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    detalle = tmp_path / "detalle.csv"
    codigo = await consola(
        planilla=planilla_xlsx(), operador=operador.email, detalle=detalle, origen="Sintética"
    )

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Carga confirmada." in salida and "Detalle de redondeos" not in salida
    filas = list(csv.reader(detalle.open(encoding="utf-8"), delimiter=";"))
    assert filas[0] == ["tipo", "fila", "ejercicio", "nombre", "detalle"]
    assert [
        "redondeo",
        "6",
        "1990",
        "PRUEBA Ana Sintética",
        "aportes: 82466.667256 → 82466.67",
    ] in (filas)
    assert sum(1 for f in filas if f[0] == "sin_vincular") == 3
    assert await db_session.scalar(select(func.count()).select_from(PuntosAfiliado)) == 4

    await crear_escribano(db_session, "Prueba", "Ana Sintética")
    await db_session.commit()
    assert await consola(revincular=True, operador=operador.email) == 0
    assert "exactos: 1" in capsys.readouterr().out


async def test_consola_operador_invalido(
    consola: Callable[..., Any],
    planilla_xlsx: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await consola(planilla=planilla_xlsx(), operador="nadie@x.example") == 2
    assert "No hay un usuario activo" in capsys.readouterr().err


def test_main_valida_argumentos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cargar_puntos.main(["--operador", "x@y.example"])
    with pytest.raises(SystemExit):
        cargar_puntos.main(["--operador", "x@y.example", "--revincular", "--planilla", "a.xls"])
    assert (
        cargar_puntos.main(["--operador", "x@y.example", "--planilla", str(tmp_path / "no.xls")])
        == 2
    )
    assert "Planilla inválida" in capsys.readouterr().err
