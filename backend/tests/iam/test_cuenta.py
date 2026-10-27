"""Cuenta propia: cambio de contraseña desde la sesión y datos del perfil."""

from datetime import UTC, datetime, timedelta

import pyotp
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import get_settings
from app.modules.iam.models import User
from tests.conftest import CSRF_HEADERS, FakeMailer
from tests.ddjj.conftest import _escribano
from tests.iam.factories import PASSWORD, make_user
from tests.iam.test_rbac import login

NUEVA = "Otra-Clave-Segura-2026!"


async def _otro_dispositivo(app: FastAPI, user: User) -> AsyncClient:
    transport = ASGITransport(app=app, client=("203.0.113.30", 53000))
    cliente = AsyncClient(transport=transport, base_url="https://test", headers=CSRF_HEADERS)
    await login(cliente, user)
    return cliente


async def _eventos(session: AsyncSession, user: User, tipo: str) -> int:
    filas = await session.scalars(
        select(AuditSecurityLog.id).where(
            AuditSecurityLog.event_type == tipo, AuditSecurityLog.target_user_id == user.id
        )
    )
    return len(filas.all())


async def test_cambiar_contrasena_cierra_las_otras_sesiones(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    otro = await _otro_dispositivo(app, user)
    assert (await otro.get("/api/v1/auth/me")).status_code == 200

    respuesta = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NUEVA},
    )
    assert respuesta.status_code == 200, respuesta.text

    # Esta sesión sigue; la del otro dispositivo, no.
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (await otro.get("/api/v1/auth/me")).status_code == 401
    await otro.aclose()
    # La clave vieja ya no entra; la nueva, sí.
    await client.post("/api/v1/auth/logout")
    viejo = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    assert viejo.status_code == 401
    nuevo = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": NUEVA}
    )
    assert nuevo.status_code == 200
    # Aviso por mail y auditoría.
    assert [m.subject for m in mailer.sent] == ["Se cambió tu contraseña · Suite Notarial"]
    assert "tus otras sesiones abiertas" in mailer.sent[0].html
    assert await _eventos(db_session, user, "PASSWORD_CHANGED") == 1


async def test_cambiar_contrasena_exige_la_actual_y_una_nueva_valida(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    await login(client, user)

    mal = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "No-Es-La-Clave-1!", "new_password": NUEVA},
    )
    assert mal.status_code == 422
    assert mal.json()["detail"] == "La contraseña actual no es correcta."
    await db_session.refresh(user)
    # Cuenta para el bloqueo, como un ingreso fallido.
    assert user.failed_login_attempts == 1

    igual = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert igual.status_code == 422
    debil = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "corta"},
    )
    assert debil.status_code == 422
    assert mailer.sent == []
    assert await _eventos(db_session, user, "PASSWORD_CHANGED") == 0


async def test_sin_sesion_no_se_cambia_nada(client: AsyncClient) -> None:
    respuesta = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NUEVA},
    )
    assert respuesta.status_code == 401
    assert (
        await client.patch("/api/v1/auth/perfil", json={"phone_number": "1"})
    ).status_code == 401


async def test_perfil_del_personal(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    await login(client, user, secret)

    perfil = (await client.get("/api/v1/auth/perfil")).json()
    assert perfil["nombre_editable"] is True
    assert perfil["email"] == user.email

    cambio = await client.patch(
        "/api/v1/auth/perfil",
        json={"full_name": "Nombre Corregido", "phone_number": " 264 555-0101 "},
    )
    assert cambio.status_code == 200, cambio.text
    assert cambio.json()["full_name"] == "Nombre Corregido"
    assert cambio.json()["phone_number"] == "264 555-0101"
    assert (await client.get("/api/v1/auth/me")).json()["full_name"] == "Nombre Corregido"
    assert await _eventos(db_session, user, "USER_PROFILE_UPDATED") == 1
    # Vaciar el teléfono lo borra.
    vacio = await client.patch("/api/v1/auth/perfil", json={"phone_number": ""})
    assert vacio.json()["phone_number"] is None


async def test_el_nombre_de_un_escribano_lo_lleva_el_padron(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await _escribano(db_session, "Padrón", user)
    await db_session.commit()
    await login(client, user)

    assert (await client.get("/api/v1/auth/perfil")).json()["nombre_editable"] is False
    nombre = await client.patch("/api/v1/auth/perfil", json={"full_name": "Otro Nombre"})
    assert nombre.status_code == 403
    telefono = await client.patch("/api/v1/auth/perfil", json={"phone_number": "264 555-0202"})
    assert telefono.status_code == 200
    assert telefono.json()["phone_number"] == "264 555-0202"


async def test_el_bloqueo_vale_tambien_para_cambiar_la_contrasena(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    intentos = get_settings().LOGIN_MAX_ATTEMPTS
    for _ in range(intentos):
        mal = await client.post(
            "/api/v1/auth/password/change",
            json={"current_password": "No-Es-La-Clave-1!", "new_password": NUEVA},
        )
        assert mal.status_code in (401, 422)
    # Al llegar al bloqueo se cerraron todas las sesiones, también la que probaba.
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    await db_session.refresh(user)
    assert user.locked_until is not None
    # Y con la cuenta bloqueada, ni la clave correcta sirve para cambiarla ni para entrar.
    reingreso = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    assert reingreso.status_code == 401


async def test_con_la_cuenta_bloqueada_no_se_cambia_ni_con_la_clave_correcta(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    await db_session.commit()
    respuesta = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NUEVA},
    )
    assert respuesta.status_code == 429
    await db_session.refresh(user)
    assert await _eventos(db_session, user, "PASSWORD_CHANGED") == 0
