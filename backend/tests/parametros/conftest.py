from collections.abc import AsyncIterator

import pyotp
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import CSRF_HEADERS
from tests.iam.factories import make_user
from tests.iam.test_rbac import login


async def _admin_client(
    app: FastAPI, db_session: AsyncSession, ip: str
) -> AsyncIterator[AsyncClient]:
    """Cliente con sesión de un administrador distinto (2FA hecho): cuatro ojos en los tests."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(ip, 52000)),
        base_url="https://test",
        headers=CSRF_HEADERS,
    ) as client:
        await login(client, user, secret)
        yield client


@pytest.fixture
async def proponente(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async for client in _admin_client(app, db_session, "203.0.113.31"):
        yield client


@pytest.fixture
async def aprobador(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async for client in _admin_client(app, db_session, "203.0.113.32"):
        yield client
