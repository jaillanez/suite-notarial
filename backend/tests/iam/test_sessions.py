from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import UserSession
from tests.iam.factories import make_user, replace_cookie
from tests.iam.test_rbac import login


async def test_refresh_rotates_tokens(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await login(client, user)
    old_refresh = client.cookies.get("sn_refresh")

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert client.cookies.get("sn_refresh") != old_refresh
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_reused_refresh_revokes_family(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await login(client, user)
    stolen = client.cookies.get("sn_refresh")
    assert stolen is not None
    await client.post("/api/v1/auth/refresh")
    # Fuera de la ventana de concurrencia: el refresh viejo ya no puede ser otra pestaña.
    await db_session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.rotated_at.is_not(None))
        .values(rotated_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()
    legit_refresh = client.cookies.get("sn_refresh")

    replace_cookie(client, "sn_refresh", stolen, "/api/v1/auth")
    attack = await client.post("/api/v1/auth/refresh")
    assert attack.status_code == 401

    replace_cookie(client, "sn_refresh", legit_refresh or "", "/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    alive = await db_session.scalar(
        select(UserSession.id).where(
            UserSession.user_id == user.id, UserSession.is_revoked.is_(False)
        )
    )
    assert alive is None
    critical = await db_session.scalar(
        select(AuditSecurityLog.severity).where(
            AuditSecurityLog.event_type == "SESSION_REUSE_DETECTED",
            AuditSecurityLog.target_user_id == user.id,
        )
    )
    assert critical == "CRITICAL"


async def test_logout_invalidates_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    access = client.cookies.get("sn_access")

    assert (await client.post("/api/v1/auth/logout")).status_code == 204

    replace_cookie(client, "sn_access", access or "", "/api")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_csrf_header_is_required(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await login(client, user)

    no_header = await client.post("/api/v1/auth/logout", headers={"X-Requested-With": ""})
    foreign_origin = await client.post(
        "/api/v1/auth/logout", headers={"Origin": "https://sitio-malicioso.example"}
    )

    assert no_header.status_code == 403
    assert foreign_origin.status_code == 403
    assert (await client.get("/api/v1/auth/me")).status_code == 200
