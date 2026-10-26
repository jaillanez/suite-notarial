"""Migración con lotes sintéticos sobre la transacción de cada test (todo se revierte)."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.modules.iam.models import User
from app.modules.migracion import sintetico
from app.modules.migracion.homologacion import EJEMPLO
from tests.ddjj.conftest import _client
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.reportes.conftest import auditor  # noqa: F401 - fixture compartida


@pytest.fixture
def maker(db_transaction: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Sesiones de la migración sobre la transacción del test (commit = savepoint)."""
    return async_sessionmaker(
        bind=db_transaction, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
async def operador(db_session: AsyncSession) -> User:
    return await make_user(db_session, roles=("ROLE_ADMIN",))


@pytest.fixture
def lote(tmp_path: Path) -> Callable[..., Path]:
    def generar(nombre: str = "lote", **opciones: Any) -> Path:
        directorio = tmp_path / nombre
        sintetico.generar(directorio, **({"registros": 6} | opciones))
        return directorio

    return generar


@pytest.fixture
def homologacion_aprobada(tmp_path: Path) -> Path:
    """Una tabla distinta de la de ejemplo (la de ejemplo más un código), sin marca de ejemplo:
    la aprueban las conformidades sobre un simulacro que la usó."""
    datos = json.loads(EJEMPLO.read_text(encoding="utf-8"))
    datos["es_ejemplo"] = False
    datos["estado_escribano"]["APROBADO"] = "ACTIVO"
    ruta = tmp_path / "homologacion.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


@pytest.fixture
def simulacros_minimos(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    def fijar(n: int) -> None:
        original = get_settings()
        monkeypatch.setattr(
            "app.modules.migracion.service.get_settings",
            lambda: original.model_copy(update={"MIGRACION_SIMULACROS_MINIMOS": n}),
        )

    return fijar


@dataclass
class Firmante:
    client: AsyncClient
    user: User


async def _firmante(app: FastAPI, db_session: AsyncSession, rol: str) -> AsyncIterator[Firmante]:
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=(rol,), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield Firmante(ac, user)


@pytest.fixture
async def notario_cliente(client: AsyncClient, db_session: AsyncSession) -> AsyncClient:
    await login(client, await make_user(db_session))
    return client


@pytest.fixture
async def tesoreria(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[Firmante]:
    async for f in _firmante(app, db_session, "ROLE_TESORERIA"):
        yield f


@pytest.fixture
async def caja(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[Firmante]:
    async for f in _firmante(app, db_session, "ROLE_CAJA"):
        yield f
