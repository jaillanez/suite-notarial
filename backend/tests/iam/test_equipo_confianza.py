"""«No volver a pedir el código en este equipo» (pedido del 22/11/2026)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sha256_hex
from app.modules.iam.models import TrustedDevice
from tests.conftest import FakeMailer
from tests.iam.factories import PASSWORD, make_user, replace_cookie, take_login_code
from tests.iam.test_rbac import login

NUEVA = "Otra-Clave-Segura-2026!"


async def _password(client: AsyncClient, email: str, password: str = PASSWORD) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/login", json={"identifier": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def _recordar(client: AsyncClient, email: str) -> str:
    """Ingreso completo marcando «recordar este equipo»; devuelve el token de la cookie."""
    await _password(client, email)
    ok = await client.post(
        "/api/v1/auth/login/mfa",
        json={"code": take_login_code(client), "recordar_equipo": True},
    )
    assert ok.status_code == 200, ok.text
    cookie = next(c for c in ok.headers.get_list("set-cookie") if c.startswith("sn_equipo="))
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Path=/api/v1/auth/login" in cookie
    token = client.cookies.get("sn_equipo")
    assert token is not None
    return token


async def test_el_equipo_recordado_entra_sin_codigo(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    token = await _recordar(client, user.email)
    # El token no se guarda en claro.
    guardado = await db_session.scalar(
        select(TrustedDevice.token_hash).where(TrustedDevice.user_id == user.id)
    )
    assert guardado == sha256_hex(token)

    await client.post("/api/v1/auth/logout")
    enviados = len(mailer.sent)
    step = await _password(client, user.email)

    assert step["status"] == "authenticated"
    assert step["user"]["mfa_verified"] is True  # type: ignore[index]
    assert len(mailer.sent) == enviados
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200


async def test_sin_marcar_la_casilla_se_sigue_pidiendo(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    assert client.cookies.get("sn_equipo") is None
    await client.post("/api/v1/auth/logout")

    assert (await _password(client, user.email))["status"] == "mfa_required"


async def test_el_equipo_de_otra_cuenta_no_sirve(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mia = await make_user(db_session)
    otra = await make_user(db_session)
    await _recordar(client, mia.email)
    await client.post("/api/v1/auth/logout")

    assert (await _password(client, otra.email))["status"] == "mfa_required"


async def test_la_contrasena_sigue_siendo_obligatoria(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await _recordar(client, user.email)
    await client.post("/api/v1/auth/logout")

    mal = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": "Incorrecta-123!"}
    )
    assert mal.status_code == 401


async def test_vencido_o_falsificado_vuelve_a_pedir(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    token = await _recordar(client, user.email)
    await client.post("/api/v1/auth/logout")

    replace_cookie(client, "sn_equipo", "inventado", "/api/v1/auth/login")
    assert (await _password(client, user.email))["status"] == "mfa_required"
    take_login_code(client)

    replace_cookie(client, "sn_equipo", token, "/api/v1/auth/login")
    await db_session.execute(
        update(TrustedDevice)
        .where(TrustedDevice.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()
    assert (await _password(client, user.email))["status"] == "mfa_required"


async def test_cambiar_la_contrasena_olvida_los_equipos(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await _recordar(client, user.email)
    cambio = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NUEVA},
    )
    assert cambio.status_code == 200, cambio.text
    await client.post("/api/v1/auth/logout")

    assert (await _password(client, user.email, NUEVA))["status"] == "mfa_required"
    motivo = await db_session.scalar(
        select(TrustedDevice.revoked_reason).where(TrustedDevice.user_id == user.id)
    )
    assert motivo == "password_changed"
