import uuid

from httpx import AsyncClient

from app.core.middleware import SECURITY_HEADERS


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


async def test_correlation_id_generated(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    uuid.UUID(response.headers["X-Correlation-ID"])


async def test_correlation_id_propagated(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Correlation-ID": "req-abc_123.x"})

    assert response.headers["X-Correlation-ID"] == "req-abc_123.x"


async def test_unsafe_correlation_id_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Correlation-ID": "a b\tinyectado"})

    uuid.UUID(response.headers["X-Correlation-ID"])


async def test_problem_details_carry_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/api/no-existe", headers={"X-Correlation-ID": "trace-1"})

    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == "trace-1"
    assert response.json()["correlation_id"] == "trace-1"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
