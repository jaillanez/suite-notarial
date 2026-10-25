import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import User
from tests.iam.factories import PASSWORD, make_user, replace_cookie, totp_code


async def login(client: AsyncClient, user: User, secret: str | None = None) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    if secret:
        mfa = await client.post("/api/v1/auth/login/mfa", json={"code": totp_code(secret)})
        assert mfa.status_code == 200


async def test_protected_endpoint_requires_session(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


async def test_missing_permission_is_403_and_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await login(client, user)

    response = await client.get("/api/v1/users")

    assert response.status_code == 403
    assert response.json()["missing_permissions"] == ["users:read"]
    denied = (
        await db_session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "PERMISSION_DENIED",
                AuditSecurityLog.actor_user_id == user.id,
            )
        )
    ).scalar_one()
    assert denied.details == {"missing": ["users:read"], "path": "GET /api/v1/users"}


async def test_forged_token_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session, roles=("ROLE_ADMIN",))
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "mfa": True,
            "typ": "access",
            "iss": "suite-notarial",
            "aud": "suite-notarial-api",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "jti": "x",
        },
        "otra-clave-que-no-es-la-del-servidor-0123456789",
        algorithm="HS256",
    )
    replace_cookie(client, "sn_access", forged, "/api")

    response = await client.get("/api/v1/users")
    assert response.status_code == 401
    assert len([c for c in client.cookies.jar if c.name == "sn_access"]) == 1


async def test_role_scope_is_enforced(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    caja = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    target = await make_user(db_session)
    await login(client, caja, secret)

    assert (await client.get("/api/v1/users")).status_code == 200
    suspend = await client.patch(
        f"/api/v1/users/{target.id}/status", json={"is_active": False, "reason": "Prueba"}
    )
    assert suspend.status_code == 403
    assert (await client.get("/api/v1/audit/security-logs")).status_code == 403


async def test_auditor_reads_audit_log(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    auditor = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    await login(client, auditor, secret)

    response = await client.get(
        "/api/v1/audit/security-logs", params={"user_id": str(auditor.id), "page_size": 5}
    )

    assert response.status_code == 200
    events = [item["event_type"] for item in response.json()["items"]]
    assert "LOGIN_SUCCESS" in events
