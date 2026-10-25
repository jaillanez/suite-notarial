from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.common.cuit import format_cuit
from app.modules.iam.models import User
from app.modules.iam.service import INVALID_CREDENTIALS
from tests.iam.factories import PASSWORD, make_user


async def _events(session: AsyncSession, user: User) -> list[str]:
    result = await session.execute(
        select(AuditSecurityLog.event_type)
        .where(
            (AuditSecurityLog.target_user_id == user.id)
            | (AuditSecurityLog.actor_user_id == user.id)
        )
        .order_by(AuditSecurityLog.event_timestamp)
    )
    return list(result.scalars())


async def test_login_sets_hardened_cookies(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    response = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "authenticated"
    assert response.json()["user"]["roles"] == ["ROLE_ESCRIBANO"]
    cookies = response.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith("sn_access="))
    refresh = next(c for c in cookies if c.startswith("sn_refresh="))
    for cookie in (access, refresh):
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
    assert "SameSite=lax" in access
    assert "Path=/api" in access
    assert "SameSite=strict" in refresh
    assert "Path=/api/v1/auth" in refresh

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == user.email


async def test_login_by_formatted_cuit(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    response = await client.post(
        "/api/v1/auth/login", json={"identifier": format_cuit(user.cuit), "password": PASSWORD}
    )

    assert response.status_code == 200


async def test_failures_are_indistinguishable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    suspended = await make_user(db_session, is_active=False)

    responses = [
        await client.post(
            "/api/v1/auth/login", json={"identifier": user.email, "password": "Incorrecta-123!"}
        ),
        await client.post(
            "/api/v1/auth/login",
            json={"identifier": "nadie@suite-notarial.example", "password": PASSWORD},
        ),
        await client.post(
            "/api/v1/auth/login", json={"identifier": suspended.email, "password": PASSWORD}
        ),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.json()["detail"] == INVALID_CREDENTIALS
        assert "set-cookie" not in response.headers


async def test_lockout_after_max_attempts(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"identifier": user.email, "password": "Incorrecta-123!"}
        )
    blocked = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )

    assert blocked.status_code == 401
    assert blocked.json()["detail"] == INVALID_CREDENTIALS
    await db_session.refresh(user)
    assert user.locked_until is not None
    assert user.locked_until > datetime.now(UTC) + timedelta(minutes=14)
    assert "LOGIN_LOCKED" in await _events(db_session, user)

    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    unlocked = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    assert unlocked.status_code == 200


async def test_success_is_audited_with_ip(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)

    await client.post("/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD})

    row = (
        await db_session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "LOGIN_SUCCESS",
                AuditSecurityLog.actor_user_id == user.id,
            )
        )
    ).scalar_one()
    assert str(row.ip_address) == "203.0.113.10"
    assert row.correlation_id is not None
    assert row.event_timestamp.tzinfo is not None
