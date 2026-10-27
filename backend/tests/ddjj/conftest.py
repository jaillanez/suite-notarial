"""Escenario de DDJJ: parámetros 2026 relevados, calendario de vencimientos y un registro
sintético con titular y adscripto. "Hoy" queda fijo en el 23/10/2026 (fecha de la boleta 1069)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ddjj import service as ddjj_service
from app.modules.ddjj.models import Vencimiento
from app.modules.iam.models import User
from app.modules.padron.models import (
    Adscripcion,
    Circunscripcion,
    Escribano,
    Persona,
    RegistroNotarial,
)
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.parametros.sistema_actual import CONCEPTOS, VENCIMIENTOS_2026
from tests.conftest import CSRF_HEADERS
from tests.iam.factories import make_user, synthetic_cuit
from tests.iam.test_rbac import login

HOY = date(2026, 10, 23)
_numeros = iter(range(7_000, 100_000))


@pytest.fixture(autouse=True)
def hoy(monkeypatch: pytest.MonkeyPatch) -> date:
    monkeypatch.setattr(ddjj_service, "today_local", lambda: HOY)
    return HOY


@pytest.fixture
async def parametros_2026(
    db_session: AsyncSession, request: pytest.FixtureRequest
) -> dict[str, uuid.UUID]:
    """Carga los tramos relevados como vigencias aprobadas. Devuelve concepto -> id.

    `@pytest.mark.ejemplo("CONCEPTO", ...)` marca esos conceptos como valores de ejemplo."""
    marca = request.node.get_closest_marker("ejemplo")
    de_ejemplo = set(marca.args) if marca else set()
    autor = await make_user(db_session, roles=("ROLE_ADMIN",))
    aprobador = await make_user(db_session, roles=("ROLE_ADMIN",))
    ids: dict[str, uuid.UUID] = {}
    for relevado in CONCEPTOS:
        concepto = Concepto(
            id=uuid.uuid4(), codigo=relevado.codigo, nombre=relevado.nombre, tipo=relevado.tipo
        )
        db_session.add(concepto)
        ids[relevado.codigo] = concepto.id
        for version, tramo in enumerate(relevado.tramos, start=1):
            db_session.add(
                Vigencia(
                    concepto_id=concepto.id,
                    version=version,
                    fecha_desde=tramo.desde,
                    fecha_hasta=tramo.hasta,
                    **tramo.valores,
                    es_ejemplo=tramo.a_confirmar or relevado.codigo in de_ejemplo,
                    estado="VIGENTE",
                    resolucion_respaldo="Sistema actual",
                    motivo="Carga de prueba",
                    created_by_user_id=autor.id,
                    aprobado_por_user_id=aprobador.id,
                )
            )
    for mes, fecha in VENCIMIENTOS_2026.items():
        db_session.add(Vencimiento(periodo=f"2026-{mes:02d}", fecha_vencimiento=fecha))
    await db_session.commit()
    return ids


async def _escribano(session: AsyncSession, apellido: str, user: User | None = None) -> Escribano:
    persona = Persona(
        id=uuid.uuid4(),
        cuit=synthetic_cuit(),
        numero_documento="30111222",
        apellido=apellido,
        nombre="Sintético",
    )
    session.add(persona)
    escribano = Escribano(
        id=uuid.uuid4(),
        persona_id=persona.id,
        user_id=user.id if user else None,
        matricula_numero=next(_numeros),
        fecha_matriculacion=date(2010, 1, 1),
        estado_matricula="ACTIVO",
    )
    session.add(escribano)
    await session.flush()
    return escribano


@dataclass
class Escenario:
    registro: RegistroNotarial
    titular: Escribano
    adscripto: Escribano
    titular_user: User
    otro_registro: RegistroNotarial


@pytest.fixture
async def escenario(db_session: AsyncSession, parametros_2026: dict[str, uuid.UUID]) -> Escenario:
    circ = Circunscripcion(id=uuid.uuid4(), nombre=f"Circ. DDJJ {next(_numeros)}")
    db_session.add(circ)
    registros = []
    for _ in range(2):
        r = RegistroNotarial(
            id=uuid.uuid4(),
            numero_registro=next(_numeros),
            circunscripcion_id=circ.id,
            departamento="Capital",
            domicilio_legal="Calle de Prueba 123",
        )
        db_session.add(r)
        registros.append(r)
    await db_session.flush()
    titular_user = await make_user(db_session)
    titular = await _escribano(db_session, "Titular", titular_user)
    adscripto = await _escribano(db_session, "Adscripto")
    for esc, cargo in ((titular, "TITULAR"), (adscripto, "ADSCRIPTO")):
        db_session.add(
            Adscripcion(
                escribano_id=esc.id,
                registro_id=registros[0].id,
                cargo=cargo,
                fecha_desde=date(2020, 1, 1),
            )
        )
    await db_session.commit()
    return Escenario(registros[0], titular, adscripto, titular_user, registros[1])


async def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app, client=("203.0.113.20", 52000))
    return AsyncClient(transport=transport, base_url="https://test", headers=CSRF_HEADERS)


@pytest.fixture
async def notario(app: FastAPI, escenario: Escenario) -> AsyncIterator[AsyncClient]:
    """Sesión del escribano titular del registro (autogestión)."""
    async with await _client(app) as ac:
        await login(ac, escenario.titular_user)
        yield ac


@pytest.fixture
async def staff(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Sesión de Administración de Caja, con 2FA."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


def escritura(escribano: Escribano, numero: int, base: str, **extra: Any) -> dict[str, Any]:
    return {
        "escribano_id": str(escribano.id),
        "numero_escritura": numero,
        "fecha_acto": "2026-09-15",
        "naturaleza": "Compraventa",
        "categoria": "ESCRITURA_CON_VALOR",
        "base_imponible": base,
        **extra,
    }
