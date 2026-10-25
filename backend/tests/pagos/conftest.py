# Las fixtures de DDJJ se importan para reusarlas; ruff las ve como redefiniciones.
# ruff: noqa: F811
"""Escenario de pagos: el de DDJJ más una boleta presentada y una sesión de Tesorería."""

import io
from collections.abc import AsyncIterator
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pagos import service as pagos_service
from tests.ddjj.conftest import (  # noqa: F401 - fixtures compartidas
    HOY,
    Escenario,
    _client,
    escenario,
    escritura,
    hoy,
    notario,
    parametros_2026,
    staff,
)
from tests.iam.factories import make_user
from tests.iam.test_rbac import login

PDF = (
    b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n"
    b"trailer << /Root 1 0 R >>\n%%EOF\n"
)


@pytest.fixture(autouse=True)
def hoy_pagos(monkeypatch: pytest.MonkeyPatch, hoy: object) -> None:
    monkeypatch.setattr(pagos_service, "today_local", lambda: HOY)


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (17, 51, 71)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
async def tesoreria(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Sesión de Tesorería (comprobantes:verify), con 2FA."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_TESORERIA",), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


@pytest.fixture
async def boleta(notario: AsyncClient, escenario: Escenario) -> dict[str, Any]:
    """Boleta pendiente de la DDJJ 09/2026, con pago hasta el 23/10/2026."""
    ddjj = (
        await notario.post(
            "/api/v1/ddjj/declaraciones",
            json={"registro_id": str(escenario.registro.id), "periodo": "2026-09"},
        )
    ).json()
    await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos",
        json=escritura(escenario.titular, 1, "100000000.00"),
    )
    response = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def adjuntar(
    client: AsyncClient,
    boleta: dict[str, Any],
    *,
    contenido: bytes = PDF,
    nombre: str = "transferencia.pdf",
    tipo: str = "application/pdf",
    importe: str | None = None,
    fecha: str = "2026-10-23",
) -> Any:
    return await client.post(
        f"/api/v1/pagos/boletas/{boleta['id']}/comprobantes",
        data={
            "fecha_transferencia": fecha,
            "numero_operacion": "OP-123456",
            "importe_declarado": importe or boleta["total_a_pagar"],
            "banco_origen": "Banco de prueba",
        },
        files={"archivo": (nombre, contenido, tipo)},
    )
