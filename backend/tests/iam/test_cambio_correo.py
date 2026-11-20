"""Cambio del correo de ingreso desde Mi cuenta y validación del teléfono (pedido de la Caja,
20/11/2026). El correo cambia recién al confirmar el enlace que llega a la dirección nueva."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.security import sha256_hex
from app.modules.iam.models import EmailChangeToken, User
from tests.conftest import FakeMailer
from tests.iam.factories import PASSWORD, make_user
from tests.iam.test_rbac import login

LINK_RE = re.compile(r"https://suite\.cajanotarial-sj\.test/confirmar-correo#token=([\w-]+)")
NUEVO = "nuevo.correo@suite-notarial.example"


async def _pedir(client: AsyncClient, email: str = NUEVO, password: str = PASSWORD) -> object:
    return await client.post(
        "/api/v1/auth/perfil/correo", json={"nuevo_email": email, "password": password}
    )


async def _token(mailer: FakeMailer) -> str:
    match = LINK_RE.search(mailer.sent[-1].text)
    assert match is not None, mailer.sent[-1].text
    return match.group(1)


async def test_cambio_de_correo_con_confirmacion(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    anterior = user.email
    await login(client, user)

    pedido = await _pedir(client, NUEVO.upper())
    assert pedido.status_code == 202, pedido.text  # type: ignore[attr-defined]
    assert [m.to for m in mailer.sent] == [NUEVO]
    mail = mailer.sent[-1]
    assert "localhost" not in mail.text + mail.html
    token = await _token(mailer)
    filtro = EmailChangeToken.user_id == user.id
    guardado = (await db_session.scalars(select(EmailChangeToken).where(filtro))).one()
    assert guardado.token_hash == sha256_hex(token) and guardado.nuevo_email == NUEVO
    # Hasta confirmar, sigue el correo anterior.
    assert (await client.get("/api/v1/auth/perfil")).json()["email"] == anterior

    confirmado = await client.post("/api/v1/auth/perfil/correo/confirmar", json={"token": token})
    assert confirmado.status_code == 200, confirmado.text
    assert (await client.get("/api/v1/auth/perfil")).json()["email"] == NUEVO
    # Se avisa a la dirección anterior.
    assert mailer.sent[-1].to == anterior
    # El enlace es de un solo uso.
    otra_vez = await client.post("/api/v1/auth/perfil/correo/confirmar", json={"token": token})
    assert otra_vez.status_code == 400
    eventos = (
        await db_session.scalars(
            select(AuditSecurityLog.event_type).where(AuditSecurityLog.target_user_id == user.id)
        )
    ).all()
    assert {"EMAIL_CHANGE_REQUESTED", "EMAIL_CHANGED", "EMAIL_CHANGE_REJECTED"} <= set(eventos)


async def test_cambio_de_correo_exige_la_contrasena_y_un_correo_libre(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    otro = await make_user(db_session)
    await login(client, user)

    mala = await _pedir(client, password="no-es-la-clave")
    assert mala.status_code == 422  # type: ignore[attr-defined]
    ocupado = await _pedir(client, otro.email)
    assert ocupado.status_code == 409  # type: ignore[attr-defined]
    mismo = await _pedir(client, user.email)
    assert mismo.status_code == 422  # type: ignore[attr-defined]
    assert mailer.sent == []


async def test_el_correo_tomado_mientras_tanto_no_se_confirma(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    assert (await _pedir(client)).status_code == 202  # type: ignore[attr-defined]
    token = await _token(mailer)
    await make_user(db_session, email=NUEVO)

    respuesta = await client.post("/api/v1/auth/perfil/correo/confirmar", json={"token": token})
    assert respuesta.status_code == 409
    assert (await db_session.get(User, user.id)) is not None


async def test_sin_sesion_no_se_pide_el_cambio(client: AsyncClient) -> None:
    assert (await _pedir(client)).status_code == 401  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("telefono", "valido"),
    [
        ("264 427-6426", True),
        ("(0264) 4276426", True),
        ("+54 9 264 427 6426", True),
        ("abc123", False),
        ("264-ABC-1234", False),
        ("12345", False),
        ("1234567890123456", False),
        ("264 # 4276426", False),
        ("26+44276426", False),
    ],
)
async def test_telefono_solo_numeros(
    client: AsyncClient, db_session: AsyncSession, telefono: str, valido: bool
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    respuesta = await client.patch("/api/v1/auth/perfil", json={"phone_number": telefono})
    assert respuesta.status_code == (200 if valido else 422), respuesta.text
