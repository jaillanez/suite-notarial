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
    assert "X-Client-Correlation-ID" not in response.headers


async def test_client_cannot_set_authoritative_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Correlation-ID": "req-abc_123.x"})

    assert response.headers["X-Correlation-ID"] != "req-abc_123.x"
    uuid.UUID(response.headers["X-Correlation-ID"])
    assert response.headers["X-Client-Correlation-ID"] == "req-abc_123.x"


async def test_each_request_gets_its_own_id(client: AsyncClient) -> None:
    headers = {"X-Correlation-ID": "mismo-id"}
    first = await client.get("/api/health", headers=headers)
    second = await client.get("/api/health", headers=headers)

    assert first.headers["X-Correlation-ID"] != second.headers["X-Correlation-ID"]


async def test_unsafe_client_correlation_id_dropped(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Correlation-ID": "a b\tinyectado"})

    uuid.UUID(response.headers["X-Correlation-ID"])
    assert "X-Client-Correlation-ID" not in response.headers


async def test_problem_details_carry_server_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/api/no-existe", headers={"X-Correlation-ID": "trace-1"})

    assert response.status_code == 404
    assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]
    assert response.json()["correlation_id"] != "trace-1"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
