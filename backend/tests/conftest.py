"""Fixtures compartidas. Los tests corren contra la base `suite_notarial_test`."""

import os
from collections.abc import AsyncIterator

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://suite_app:suite_app_dev@localhost:5432/suite_notarial_test",
)
os.environ.setdefault("PUBLIC_WEB_URL", "http://localhost:5173")
os.environ.setdefault("JWT_SECRET", "test-secret-no-usar-en-produccion-0123456789")
# Clave fija de test (32 bytes de 0x01): no es un secreto.
os.environ.setdefault("DATA_ENCRYPTION_KEY", "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
