"""Fixtures compartidas.

Los tests corren contra `suite_notarial_test`: el esquema se crea con las migraciones reales
(rol dueño) y la app se conecta con el rol de aplicación, igual que en producción. Cada test
corre dentro de una transacción que se revierte al terminar.
"""

import os
import tempfile
from collections.abc import AsyncIterator

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://suite_app:suite_app_dev@localhost:5432/suite_notarial_test",
)
os.environ.setdefault(
    "MIGRATIONS_DATABASE_URL",
    "postgresql+asyncpg://suite_owner:suite_owner_dev@localhost:5432/suite_notarial_test",
)
os.environ.setdefault("PUBLIC_WEB_URL", "https://suite.cajanotarial-sj.test")
os.environ.setdefault("JWT_SECRET", "test-secret-no-usar-en-produccion-0123456789")
# Clave fija de test (32 bytes de 0x01): no es un secreto.
os.environ.setdefault("DATA_ENCRYPTION_KEY", "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=")
os.environ.setdefault("COOKIE_SECURE", "true")
# Comprobantes de los tests en un directorio temporal propio de la corrida.
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="suite-notarial-uploads-")
# Los tests corren siempre con 2FA exigido, aunque el .env local lo tenga apagado.
os.environ["MFA_ENFORCED"] = "true"

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.mail import OutgoingMail
from app.db.session import get_session
from app.main import create_app
from app.modules.iam.router_auth import get_mailer

BACKEND_DIR = Path(__file__).resolve().parents[1]
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    async def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Aplica las migraciones una vez por corrida (downgrade + upgrade: valida reversibilidad)."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def db_connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(str(get_settings().DATABASE_URL))
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
async def db_transaction(db_connection: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    transaction = await db_connection.begin()
    try:
        yield db_connection
    finally:
        await transaction.rollback()


@pytest.fixture
async def db_session(db_transaction: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(
        bind=db_transaction, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def app(db_transaction: AsyncConnection, mailer: FakeMailer) -> FastAPI:
    application = create_app()

    async def session_override() -> AsyncIterator[AsyncSession]:
        # Una sesión nueva por request, sobre la transacción del test.
        async with AsyncSession(
            bind=db_transaction, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_mailer] = lambda: mailer
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # HTTPS para que el cliente envíe las cookies marcadas Secure, como un navegador real.
    transport = ASGITransport(app=app, client=("203.0.113.10", 51000))
    async with AsyncClient(
        transport=transport, base_url="https://test", headers=CSRF_HEADERS
    ) as ac:
        yield ac
