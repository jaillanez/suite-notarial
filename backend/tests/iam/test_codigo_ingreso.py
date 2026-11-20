"""Código de ingreso por correo (pedido de la Caja, 20/11/2026): en cada ingreso, quien no tiene
la aplicación de autenticación recibe un código de 6 dígitos que vence y sirve una sola vez."""

from datetime import UTC, datetime, timedelta

import pyotp
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import LoginEmailCode, UserSession
from app.modules.iam.service import INVALID_MFA, MAX_LOGIN_CODES, TOO_MANY_LOGIN_CODES
from tests.conftest import FakeMailer
from tests.iam.factories import (
    PASSWORD,
    make_user,
    replace_cookie,
    take_login_code,
)
from tests.iam.test_rbac import login


async def _password(client: AsyncClient, email: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_el_codigo_llega_al_correo_y_abre_la_sesion(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session, email="horacio@suite-notarial.example")

    step = await _password(client, user.email)

    assert step == {
        "status": "mfa_required",
        "user": None,
        "mfa_method": "email",
        "email_hint": "h***@suite-notarial.example",
    }
    assert "sn_access" not in client.cookies
    mail = mailer.sent[-1]
    assert mail.to == user.email
    code = take_login_code(client)
    assert code in mail.text and code in mail.html
    assert "https://suite.cajanotarial-sj.test/recuperar-clave" in mail.text
    # El código no se guarda en claro.
    stored = await db_session.scalar(
        select(LoginEmailCode.code_hash).where(LoginEmailCode.user_id == user.id)
    )
    assert stored is not None and code not in stored

    ok = await client.post("/api/v1/auth/login/mfa", json={"code": code})
    assert ok.status_code == 200
    assert ok.json()["user"]["mfa_verified"] is True
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_el_codigo_sirve_una_sola_vez(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _password(client, user.email)
    code = take_login_code(client)
    assert (await client.post("/api/v1/auth/login/mfa", json={"code": code})).status_code == 200

    # Mismo desafío (cookie) reenviado: el código ya se usó.
    await client.post("/api/v1/auth/logout")
    await _password(client, user.email)
    take_login_code(client)
    reuse = await client.post("/api/v1/auth/login/mfa", json={"code": code})
    assert reuse.status_code == 401
    assert reuse.json()["detail"] == INVALID_MFA


async def test_el_codigo_vencido_no_sirve(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _password(client, user.email)
    code = take_login_code(client)
    await db_session.execute(
        update(LoginEmailCode)
        .where(LoginEmailCode.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    response = await client.post("/api/v1/auth/login/mfa", json={"code": code})

    assert response.status_code == 401


async def test_reenviar_anula_el_codigo_anterior(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await _password(client, user.email)
    primero = take_login_code(client)

    reenvio = await client.post("/api/v1/auth/login/codigo")
    assert reenvio.status_code == 200
    assert reenvio.json()["mfa_method"] == "email"
    segundo = take_login_code(client)

    if primero != segundo:
        viejo = await client.post("/api/v1/auth/login/mfa", json={"code": primero})
        assert viejo.status_code == 401
    assert (await client.post("/api/v1/auth/login/mfa", json={"code": segundo})).status_code == 200


async def test_el_codigo_de_otro_ingreso_no_sirve(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """El desafío queda atado a su código: no sirve el de otro ingreso ni el de otra cuenta."""
    victima = await make_user(db_session)
    atacante = await make_user(db_session)
    await _password(client, atacante.email)
    take_login_code(client)
    cookie_atacante = client.cookies.get("sn_mfa")
    await _password(client, victima.email)
    take_login_code(client)

    assert cookie_atacante is not None
    replace_cookie(client, "sn_mfa", cookie_atacante, "/api/v1/auth")
    otro = await client.post("/api/v1/auth/login/mfa", json={"code": "123456"})
    assert otro.status_code == 401


async def test_varios_codigos_errados_anulan_el_codigo_y_bloquean(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await _password(client, user.email)
    code = take_login_code(client)
    errado = "000000" if code != "000000" else "111111"

    for _ in range(5):
        response = await client.post("/api/v1/auth/login/mfa", json={"code": errado})
        assert response.status_code == 401

    tarde = await client.post("/api/v1/auth/login/mfa", json={"code": code})
    assert tarde.status_code == 401
    await db_session.refresh(user)
    assert user.locked_until is not None
    eventos = await db_session.scalars(
        select(AuditSecurityLog.event_type).where(AuditSecurityLog.target_user_id == user.id)
    )
    assert "LOGIN_MFA_FAILED" in set(eventos)


async def test_limite_de_codigos_por_cuenta(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    for _ in range(MAX_LOGIN_CODES):
        await _password(client, user.email)
    enviados = len(mailer.sent)

    otro = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    assert otro.status_code == 429
    assert otro.json()["detail"] == TOO_MANY_LOGIN_CODES
    assert len(mailer.sent) == enviados
    assert (await client.post("/api/v1/auth/login/codigo")).status_code == 429


async def test_con_la_aplicacion_no_se_manda_codigo(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, totp_secret=secret)

    step = await _password(client, user.email)

    assert step["mfa_method"] == "totp"
    assert mailer.sent == []
    assert (await client.post("/api/v1/auth/login/codigo")).status_code == 401


async def test_la_sesion_abierta_sin_codigo_no_se_renueva(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Las sesiones de antes del cambio (solo contraseña) piden volver a ingresar."""
    user = await make_user(db_session)
    await login(client, user)
    await db_session.execute(
        update(UserSession).where(UserSession.user_id == user.id).values(mfa_verified=False)
    )
    await db_session.commit()

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    revocada = await db_session.scalar(
        select(UserSession.revoked_reason).where(
            UserSession.user_id == user.id, UserSession.is_revoked.is_(True)
        )
    )
    assert revocada == "mfa_not_verified"


async def test_el_codigo_por_correo_no_se_apaga_en_produccion() -> None:
    import pytest

    from app.core.config import Environment, Settings

    for env in (Environment.STAGING, Environment.PRODUCTION):
        with pytest.raises(ValueError, match="LOGIN_EMAIL_CODE"):
            Settings(
                ENVIRONMENT=env,
                PUBLIC_WEB_URL="https://suite.cajanotarial-sj.com.ar",
                SMTP_SECURITY="tls",
                LOGIN_EMAIL_CODE=False,
            )


async def test_completar_el_codigo_sin_desafio_falla(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/login/mfa", json={"code": "123456"})).status_code == 401
    assert (await client.post("/api/v1/auth/login/codigo")).status_code == 401
