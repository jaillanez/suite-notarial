import re

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import User
from tests.conftest import FakeMailer
from tests.iam.factories import PASSWORD, make_user, synthetic_cuit
from tests.iam.test_rbac import login


async def _admin(client: AsyncClient, db_session: AsyncSession) -> User:
    secret = pyotp.random_base32()
    admin = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    await login(client, admin, secret)
    return admin


async def _audit(session: AsyncSession, event: str, target: User) -> AuditSecurityLog:
    return (
        await session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == event, AuditSecurityLog.target_user_id == target.id
            )
        )
    ).scalar_one()


async def test_create_user_sends_setup_link(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    admin = await _admin(client, db_session)
    cuit = synthetic_cuit()

    response = await client.post(
        "/api/v1/users",
        json={
            "email": "Nuevo.Escribano@Suite-Notarial.example",
            "full_name": "Nuevo Escribano",
            "cuit": f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}",
            "roles": ["ROLE_ESCRIBANO"],
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "nuevo.escribano@suite-notarial.example"
    assert mailer.sent[-1].to == "nuevo.escribano@suite-notarial.example"
    assert re.search(
        r"https://suite\.cajanotarial-sj\.test/restablecer-clave#token=", mailer.sent[-1].text
    )
    created = await db_session.get(User, response.json()["id"])
    assert created is not None
    entry = await _audit(db_session, "USER_CREATED", created)
    assert entry.actor_user_id == admin.id
    assert entry.new_value is not None
    assert entry.new_value["roles"] == ["ROLE_ESCRIBANO"]


async def test_create_user_validations(client: AsyncClient, db_session: AsyncSession) -> None:
    await _admin(client, db_session)
    existing = await make_user(db_session)

    bad_cuit = await client.post(
        "/api/v1/users",
        json={
            "email": "a@suite-notarial.example",
            "full_name": "Uno",
            "cuit": "20-12345678-0",
            "roles": ["ROLE_ESCRIBANO"],
        },
    )
    duplicate = await client.post(
        "/api/v1/users",
        json={
            "email": existing.email,
            "full_name": "Dos",
            "cuit": synthetic_cuit(),
            "roles": ["ROLE_ESCRIBANO"],
        },
    )
    bad_role = await client.post(
        "/api/v1/users",
        json={
            "email": "b@suite-notarial.example",
            "full_name": "Tres",
            "cuit": synthetic_cuit(),
            "roles": ["ROLE_INVENTADO"],
        },
    )

    assert bad_cuit.status_code == 422
    assert duplicate.status_code == 409
    assert bad_role.status_code == 422


async def test_suspension_is_audited_and_blocks_login(
    client: AsyncClient, db_session: AsyncSession, app: object
) -> None:
    admin = await _admin(client, db_session)
    target = await make_user(db_session)

    response = await client.patch(
        f"/api/v1/users/{target.id}/status",
        json={"is_active": False, "reason": "Baja temporal por licencia"},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    entry = await _audit(db_session, "USER_STATUS_CHANGED", target)
    assert entry.actor_user_id == admin.id
    assert entry.old_value == {"is_active": True, "suspension_reason": None}
    assert entry.new_value == {
        "is_active": False,
        "suspension_reason": "Baja temporal por licencia",
    }

    await client.post("/api/v1/auth/logout")
    blocked = await client.post(
        "/api/v1/auth/login", json={"identifier": target.email, "password": PASSWORD}
    )
    assert blocked.status_code == 401


async def test_admin_cannot_suspend_self(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _admin(client, db_session)

    response = await client.patch(
        f"/api/v1/users/{admin.id}/status", json={"is_active": False, "reason": "Prueba propia"}
    )

    assert response.status_code == 409


async def test_role_change_is_audited(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _admin(client, db_session)
    target = await make_user(db_session)

    response = await client.put(
        f"/api/v1/users/{target.id}/roles", json={"roles": ["ROLE_ESCRIBANO", "ROLE_AUDITOR"]}
    )
    self_demote = await client.put(
        f"/api/v1/users/{admin.id}/roles", json={"roles": ["ROLE_AUDITOR"]}
    )

    assert response.status_code == 200
    assert response.json()["roles"] == ["ROLE_AUDITOR", "ROLE_ESCRIBANO"]
    entry = await _audit(db_session, "USER_ROLES_CHANGED", target)
    assert entry.old_value == {"roles": ["ROLE_ESCRIBANO"]}
    assert entry.new_value == {"roles": ["ROLE_AUDITOR", "ROLE_ESCRIBANO"]}
    assert self_demote.status_code == 409


async def test_user_list_is_paginated_in_server(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(client, db_session)
    for _ in range(3):
        await make_user(db_session)

    page = await client.get("/api/v1/users", params={"page": 1, "page_size": 2})
    filtered = await client.get("/api/v1/users", params={"is_active": "true", "q": "Prueba"})

    assert page.status_code == 200
    assert len(page.json()["items"]) == 2
    assert page.json()["total"] >= 4
    assert filtered.json()["total"] >= 4
    oversized = await client.get("/api/v1/users", params={"page_size": 1000})
    assert oversized.status_code == 422
