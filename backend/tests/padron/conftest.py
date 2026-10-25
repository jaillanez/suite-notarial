from collections.abc import Callable, Coroutine
from typing import Any

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.cuit import check_digit
from tests.iam.factories import make_user
from tests.iam.test_rbac import login

_dni = iter(range(30_000_001, 39_999_999, 7))


def valid_cuit(prefix: str = "20") -> str:
    while True:
        body = f"{prefix}{next(_dni):08d}"
        digit = check_digit(body)
        if digit is not None:
            return body + str(digit)


@pytest.fixture
async def caja(client: AsyncClient, db_session: AsyncSession) -> AsyncClient:
    """Cliente con sesión de Administración de Caja (escribanos:read/write/status), 2FA hecho."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    await login(client, user, secret)
    return client


Factory = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


@pytest.fixture
def circunscripcion(caja: AsyncClient) -> Factory:
    counter = iter(range(1, 10_000))

    async def make(nombre: str | None = None) -> dict[str, Any]:
        response = await caja.post(
            "/api/v1/padron/circunscripciones",
            json={"nombre": nombre or f"Circunscripción de prueba {next(counter)}"},
        )
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    return make


@pytest.fixture
def registro(caja: AsyncClient, circunscripcion: Factory) -> Factory:
    counter = iter(range(900, 100_000))

    async def make(numero: int | None = None, **extra: Any) -> dict[str, Any]:
        circ = await circunscripcion()
        response = await caja.post(
            "/api/v1/padron/registros",
            json={
                "numero_registro": numero or next(counter),
                "circunscripcion_id": circ["id"],
                "departamento": "Capital",
                "domicilio_legal": "Calle de Prueba 123",
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    return make


@pytest.fixture
def escribano(caja: AsyncClient) -> Factory:
    counter = iter(range(5_000, 100_000))

    async def make(**persona: Any) -> dict[str, Any]:
        response = await caja.post(
            "/api/v1/padron/escribanos",
            json={
                "persona": {
                    "cuit": valid_cuit(),
                    "numero_documento": "30111222",
                    "apellido": "Sintético",
                    "nombre": "Escribano",
                    **persona,
                },
                "matricula_numero": next(counter),
                "fecha_matriculacion": "2015-03-01",
            },
        )
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    return make
