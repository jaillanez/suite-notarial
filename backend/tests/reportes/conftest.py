"""Escenario de reportes: boletas pagadas, pendientes y anuladas, y sesiones con permisos."""

# Las fixtures se importan para reusarlas; ruff las ve como redefiniciones.
# ruff: noqa: F811

from collections.abc import AsyncIterator
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ddjj.conftest import (  # noqa: F401 - fixtures compartidas
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
from tests.pagos.conftest import (  # noqa: F401 - fixtures compartidas
    adjuntar,
    boleta,
    hoy_pagos,
    tesoreria,
)


@pytest.fixture
async def auditor(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Auditoría: reportes financieros y registro de auditoría (solo lectura), con 2FA."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


@pytest.fixture
async def datos(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    escenario: Escenario,
    boleta: dict[str, Any],
) -> dict[str, Any]:
    """Agosto pagada (con una boleta anulada antes) y septiembre pendiente."""
    agosto = (
        await notario.post(
            "/api/v1/ddjj/declaraciones",
            json={"registro_id": str(escenario.registro.id), "periodo": "2026-08"},
        )
    ).json()
    for numero, base in ((10, "50000000.00"), (11, "12345678.91")):
        await notario.post(
            f"/api/v1/ddjj/declaraciones/{agosto['id']}/actos",
            json=escritura(escenario.titular, numero, base, fecha_acto="2026-08-10"),
        )
    primera = (
        await notario.post(
            f"/api/v1/ddjj/declaraciones/{agosto['id']}/presentar",
            json={"fecha_pago": "2026-10-23"},
        )
    ).json()
    vigente = (
        await notario.post(
            f"/api/v1/ddjj/declaraciones/{agosto['id']}/boletas",
            json={"fecha_pago": "2026-10-30"},
        )
    ).json()
    comprobante = (await adjuntar(notario, vigente)).json()
    aprobada = await tesoreria.post(
        f"/api/v1/pagos/comprobantes/{comprobante['id']}/aprobar",
        json={
            "importe_confirmado": vigente["total_a_pagar"],
            "fecha_acreditacion": "2026-10-23",
            "identificador_extracto": "EXT-1",
        },
    )
    assert aprobada.status_code == 200, aprobada.text
    rechazado = (await adjuntar(notario, boleta)).json()
    await tesoreria.post(
        f"/api/v1/pagos/comprobantes/{rechazado['id']}/rechazar",
        json={"motivo": '=HYPERLINK("http://x") importe no coincide'},
    )
    return {"anulada": primera, "pagada": vigente, "pendiente": boleta}
