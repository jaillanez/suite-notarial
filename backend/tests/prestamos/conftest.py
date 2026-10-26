"""Escenario de préstamos: líneas, sesiones de Caja, Administración y Tesorería, y un "hoy"
que se puede mover para simular atrasos."""

# Las fixtures se importan para reusarlas; ruff las ve como redefiniciones.
# ruff: noqa: F811

from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.prestamos import router as prestamos_router
from app.modules.prestamos import service as prestamos_service
from tests.ddjj.conftest import (  # noqa: F401 - fixtures compartidas
    HOY,
    Escenario,
    _client,
    escenario,
    hoy,
    notario,
    parametros_2026,
    staff,
)
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.pagos.conftest import hoy_pagos, tesoreria  # noqa: F401


@pytest.fixture
def reloj(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Fija la fecha del día para préstamos (por defecto, la de los demás tests)."""

    def poner(dia: date) -> None:
        monkeypatch.setattr(prestamos_service, "today_local", lambda: dia)
        monkeypatch.setattr(prestamos_router, "today_local", lambda: dia)

    poner(HOY)
    return poner


@pytest.fixture
async def admin(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Administración: otorga y rechaza (prestamos:approve), con 2FA."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


LINEA = {
    "codigo": "LINEA_COMUN",
    "nombre": "Línea común (ejemplo)",
    "sistema": "FRANCES",
    "plazo_minimo": 6,
    "plazo_maximo": 36,
    "monto_minimo": "100000.00",
    "monto_maximo": "5000000.00",
    "tna": "12.0000",
    "afectacion_maxima": "30.0000",
    "requiere_garante": False,
    "es_ejemplo": True,
}


@pytest.fixture
def crear_linea(staff: AsyncClient) -> Callable[..., Any]:
    async def crear(**cambios: Any) -> dict[str, Any]:
        r = await staff.post("/api/v1/prestamos/lineas", json={**LINEA, **cambios})
        assert r.status_code == 201, r.text
        body: dict[str, Any] = r.json()
        return body

    return crear
