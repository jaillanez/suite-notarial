"""Transiciones de estado de matrícula y acceso de autogestión según el estado."""

from typing import Any

import pyotp
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.padron.models import Escribano
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.padron.conftest import Factory

DATE = "2026-10-01"


async def _estado(caja: AsyncClient, esc_id: str, nuevo: str, resolucion: str | None = None) -> Any:
    return await caja.post(
        f"/api/v1/padron/escribanos/{esc_id}/estado",
        json={
            "nuevo_estado": nuevo,
            "motivo": "Cambio de estado de prueba",
            "resolucion_respaldo": resolucion,
            "fecha_efectiva": DATE,
        },
    )


async def test_suspension_ends_back_to_active(caja: AsyncClient, escribano: Factory) -> None:
    esc = await escribano()

    assert (await _estado(caja, esc["id"], "SUSPENDIDO")).status_code == 200
    assert (await _estado(caja, esc["id"], "ACTIVO")).status_code == 200


async def test_jubilado_cannot_return_to_active(caja: AsyncClient, escribano: Factory) -> None:
    esc = await escribano()
    await _estado(caja, esc["id"], "JUBILADO")

    response = await _estado(caja, esc["id"], "ACTIVO")

    assert response.status_code == 409
    assert "Estados posibles: FALLECIDO" in response.json()["detail"]
    detail = (await caja.get(f"/api/v1/padron/escribanos/{esc['id']}")).json()
    assert detail["transiciones_permitidas"] == ["FALLECIDO"]


async def test_cesante_reincorporation_requires_resolution(
    caja: AsyncClient, escribano: Factory
) -> None:
    esc = await escribano()
    await _estado(caja, esc["id"], "CESANTE")
    detail = (await caja.get(f"/api/v1/padron/escribanos/{esc['id']}")).json()
    assert detail["transiciones_con_resolucion"] == ["ACTIVO"]

    without = await _estado(caja, esc["id"], "ACTIVO")
    with_resolution = await _estado(caja, esc["id"], "ACTIVO", "Res. Directorio 12/2026")

    assert without.status_code == 422
    assert with_resolution.status_code == 200


async def test_cesante_cannot_be_suspended(caja: AsyncClient, escribano: Factory) -> None:
    esc = await escribano()
    await _estado(caja, esc["id"], "CESANTE")

    assert (await _estado(caja, esc["id"], "SUSPENDIDO")).status_code == 409


async def test_suspended_escribano_can_consult_but_not_file(
    caja: AsyncClient,
    escribano: Factory,
    db_session: AsyncSession,
    app: Any,
) -> None:
    from httpx import ASGITransport

    from tests.conftest import CSRF_HEADERS

    esc = await escribano()
    user = await make_user(db_session, roles=("ROLE_ESCRIBANO",))
    await db_session.execute(
        update(Escribano).where(Escribano.id == esc["id"]).values(user_id=user.id)
    )
    await db_session.commit()

    transport = ASGITransport(app=app, client=("203.0.113.20", 51001))
    async with AsyncClient(
        transport=transport, base_url="https://test", headers=CSRF_HEADERS
    ) as own:
        await login(own, user)
        active = set((await own.get("/api/v1/auth/me")).json()["permissions"])
        assert "ddjj:create_own" in active

        await _estado(caja, esc["id"], "SUSPENDIDO")
        suspended = set((await own.get("/api/v1/auth/me")).json()["permissions"])
        assert "ddjj:create_own" not in suspended
        assert {"ddjj:read_own", "boletas:read_own", "comprobantes:upload"} <= suspended

        await _estado(caja, esc["id"], "ACTIVO")
        back = set((await own.get("/api/v1/auth/me")).json()["permissions"])
        assert "ddjj:create_own" in back


async def test_self_service_without_matricula_cannot_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session, roles=("ROLE_ESCRIBANO",))
    await login(client, user)

    permissions = set((await client.get("/api/v1/auth/me")).json()["permissions"])

    assert "ddjj:create_own" not in permissions
    assert "ddjj:read_own" in permissions


async def test_staff_permissions_unaffected(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    await login(client, user, secret)

    permissions = set((await client.get("/api/v1/auth/me")).json()["permissions"])

    assert "escribanos:status" in permissions
