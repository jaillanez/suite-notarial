"""Registro de prueba (servidor de prueba) y vínculo de cuentas existentes con el padrón."""

import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog, RequestContext
from app.core.config import Environment
from app.modules.padron import prueba
from app.modules.padron.models import (
    Adscripcion,
    Escribano,
    HistorialEstado,
    Persona,
    RegistroNotarial,
)
from tests.ddjj.conftest import Escenario, _client
from tests.iam.factories import make_user
from tests.iam.test_rbac import login

CTX = RequestContext(ip_address=None, user_agent="test", correlation_id=None, path="test")
DESDE = date(2026, 1, 1)
HOY = date(2026, 10, 23)


async def _eventos(session: AsyncSession, **filtro: object) -> list[str]:
    stmt = select(AuditSecurityLog.event_type).order_by(AuditSecurityLog.event_timestamp)
    for campo, valor in filtro.items():
        stmt = stmt.where(getattr(AuditSecurityLog, campo) == valor)
    return list((await session.scalars(stmt)).all())


async def _crear(session: AsyncSession, numero: int = 9_999) -> tuple[prueba.RegistroPrueba, str]:
    operador = await make_user(session, roles=("ROLE_ADMIN",))
    cuenta = await make_user(session)
    hecho = await prueba.crear_registro_prueba(
        session,
        CTX,
        operador,
        cuenta,
        entorno=Environment.STAGING,
        desde=DESDE,
        numero_registro=numero,
    )
    return hecho, cuenta.email


async def test_crea_registro_ficticio_con_la_cuenta_como_titular(
    db_session: AsyncSession,
) -> None:
    hecho, _ = await _crear(db_session)

    registro = await db_session.get(RegistroNotarial, hecho.registro_id)
    escribano = await db_session.get(Escribano, hecho.escribano_id)
    cargo = await db_session.scalar(
        select(Adscripcion).where(Adscripcion.escribano_id == hecho.escribano_id)
    )
    assert registro is not None and escribano is not None and cargo is not None
    assert registro.nombre_fantasia == prueba.NOMBRE_REGISTRO
    assert registro.estado == "ACTIVO"
    assert escribano.user_id == hecho.user_id
    assert escribano.estado_matricula == "ACTIVO"
    assert (cargo.cargo, cargo.fecha_desde, cargo.is_current) == ("TITULAR", DESDE, True)
    eventos = await _eventos(db_session, target_user_id=hecho.user_id)
    assert "PADRON_CUENTA_VINCULADA" in eventos


async def test_la_cuenta_vinculada_carga_ddjj_en_el_registro_de_prueba(
    app: FastAPI, db_session: AsyncSession, parametros_2026: dict[str, uuid.UUID]
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    cuenta = await make_user(db_session)
    hecho = await prueba.crear_registro_prueba(
        db_session, CTX, operador, cuenta, entorno=Environment.STAGING, desde=DESDE
    )

    async with await _client(app) as notario:
        await login(notario, cuenta)
        registros = (await notario.get("/api/v1/ddjj/registros")).json()
        ddjj = await notario.post(
            "/api/v1/ddjj/declaraciones",
            json={"registro_id": str(hecho.registro_id), "periodo": "2026-09"},
        )

    assert [r["id"] for r in registros] == [str(hecho.registro_id)]
    assert ddjj.status_code == 201
    assert ddjj.json()["puede_operar"] is True


async def test_no_se_crea_en_produccion(db_session: AsyncSession) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    cuenta = await make_user(db_session)

    with pytest.raises(prueba.PruebaError, match="solo se usa"):
        await prueba.crear_registro_prueba(
            db_session, CTX, operador, cuenta, entorno=Environment.PRODUCTION, desde=DESDE
        )
    with pytest.raises(prueba.PruebaError, match="solo se usa"):
        await prueba.baja_registro_prueba(
            db_session, CTX, operador, entorno=Environment.PRODUCTION, hoy=HOY
        )


async def test_rechaza_cuenta_sin_rol_de_escribano_o_ya_vinculada(
    db_session: AsyncSession,
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    caja = await make_user(db_session, roles=("ROLE_CAJA",))
    with pytest.raises(prueba.PruebaError, match="rol de escribano"):
        await prueba.crear_registro_prueba(
            db_session, CTX, operador, caja, entorno=Environment.STAGING, desde=DESDE
        )

    hecho, email = await _crear(db_session, numero=9_998)
    cuenta = await prueba.cuenta_por_email(db_session, email)
    with pytest.raises(prueba.PruebaError, match="ya está vinculada"):
        await prueba.crear_registro_prueba(
            db_session,
            CTX,
            operador,
            cuenta,
            entorno=Environment.STAGING,
            desde=DESDE,
            numero_registro=9_997,
        )
    assert hecho.numero_registro == 9_998


async def test_no_pisa_un_registro_existente(
    db_session: AsyncSession, escenario: Escenario
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    cuenta = await make_user(db_session)

    with pytest.raises(prueba.PruebaError, match="Ya existe un registro"):
        await prueba.crear_registro_prueba(
            db_session,
            CTX,
            operador,
            cuenta,
            entorno=Environment.STAGING,
            desde=DESDE,
            numero_registro=escenario.registro.numero_registro,
        )


async def test_baja_logica_cierra_todo_y_desvincula_sin_borrar(
    db_session: AsyncSession,
) -> None:
    hecho, email = await _crear(db_session)
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))

    await prueba.baja_registro_prueba(
        db_session, CTX, operador, entorno=Environment.STAGING, hoy=HOY
    )

    registro = await db_session.get(RegistroNotarial, hecho.registro_id)
    escribano = await db_session.get(Escribano, hecho.escribano_id)
    cargo = await db_session.scalar(
        select(Adscripcion).where(Adscripcion.escribano_id == hecho.escribano_id)
    )
    cuenta = await prueba.cuenta_por_email(db_session, email)
    assert registro is not None and escribano is not None and cargo is not None
    assert registro.estado == "CERRADO"
    assert (cargo.is_current, cargo.fecha_hasta) == (False, HOY)
    assert escribano.estado_matricula == "CESANTE"
    assert escribano.user_id is None
    assert cuenta.is_active
    historial = await db_session.scalar(
        select(HistorialEstado).where(HistorialEstado.escribano_id == hecho.escribano_id)
    )
    assert historial is not None and historial.estado_nuevo == "CESANTE"
    assert "PADRON_CUENTA_DESVINCULADA" in await _eventos(db_session, target_user_id=hecho.user_id)
    with pytest.raises(prueba.PruebaError, match="ya está dado de baja"):
        await prueba.baja_registro_prueba(
            db_session, CTX, operador, entorno=Environment.STAGING, hoy=HOY
        )


async def test_la_baja_no_toca_un_registro_real(
    db_session: AsyncSession, escenario: Escenario
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))

    with pytest.raises(prueba.PruebaError, match="no es un registro de prueba"):
        await prueba.baja_registro_prueba(
            db_session,
            CTX,
            operador,
            entorno=Environment.STAGING,
            hoy=HOY,
            numero_registro=escenario.registro.numero_registro,
        )
    assert escenario.registro.estado != "CERRADO"


async def test_vincular_cuenta_existente_con_su_escribano(
    db_session: AsyncSession, escenario: Escenario
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    cuenta = await make_user(db_session)
    persona = await db_session.get(Persona, escenario.adscripto.persona_id)
    assert persona is not None and persona.cuit is not None

    with pytest.raises(prueba.PruebaError, match="no es el del escribano"):
        await prueba.vincular_cuenta(db_session, CTX, operador, cuenta, persona.cuit)

    # La cuenta sintética toma el CUIT del adscripto: así coinciden, como en la realidad.
    cuenta.cuit = persona.cuit
    await db_session.flush()
    escribano = await prueba.vincular_cuenta(db_session, CTX, operador, cuenta, persona.cuit)

    assert escribano.id == escenario.adscripto.id
    assert escribano.user_id == cuenta.id
    assert await _eventos(db_session, target_user_id=cuenta.id) == ["PADRON_CUENTA_VINCULADA"]


async def test_vincular_rechaza_escribano_con_otra_cuenta(
    db_session: AsyncSession, escenario: Escenario
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    persona = await db_session.get(Persona, escenario.titular.persona_id)
    assert persona is not None and persona.cuit is not None
    cuenta = await make_user(db_session)
    cuenta.cuit = persona.cuit
    await db_session.flush()

    with pytest.raises(prueba.PruebaError, match="ya tiene otra cuenta"):
        await prueba.vincular_cuenta(db_session, CTX, operador, cuenta, persona.cuit)


async def test_el_operador_necesita_permiso_del_padron(
    db_session: AsyncSession, escenario: Escenario
) -> None:
    """La auditoría no puede quedar a nombre de alguien sin facultad para hacerlo."""
    sin_permiso = await make_user(db_session)  # escribano: no escribe el padrón
    cuenta = await make_user(db_session)
    persona = await db_session.get(Persona, escenario.adscripto.persona_id)
    assert persona is not None and persona.cuit is not None
    cuenta.cuit = persona.cuit
    await db_session.flush()

    with pytest.raises(prueba.PruebaError, match="no tiene permiso"):
        await prueba.crear_registro_prueba(
            db_session, CTX, sin_permiso, cuenta, entorno=Environment.STAGING, desde=DESDE
        )
    with pytest.raises(prueba.PruebaError, match="no tiene permiso"):
        await prueba.vincular_cuenta(db_session, CTX, sin_permiso, cuenta, persona.cuit)
    with pytest.raises(prueba.PruebaError, match="no tiene permiso"):
        await prueba.baja_registro_prueba(
            db_session, CTX, sin_permiso, entorno=Environment.STAGING, hoy=HOY
        )
    assert await _eventos(db_session, actor_user_id=sin_permiso.id) == []

    sin_permiso.is_active = False
    await db_session.flush()
    with pytest.raises(prueba.PruebaError, match="suspendida"):
        await prueba.vincular_cuenta(db_session, CTX, sin_permiso, cuenta, persona.cuit)
