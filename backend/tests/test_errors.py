"""Contrato RFC 7807 para errores de la API."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.errors import PROBLEM_JSON, ProblemError
from app.main import create_app


class _Payload(BaseModel):
    cantidad: int


def _app_with_test_routes() -> FastAPI:
    app = create_app()

    @app.get("/api/_test/problem")
    async def raise_problem() -> None:
        raise ProblemError(409, "Conflicto de prueba", extra={"codigo": "X1"})

    @app.post("/api/_test/validate")
    async def validate(payload: _Payload) -> _Payload:
        return payload

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("fallo inesperado")

    return app


async def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_not_found_is_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/no-existe")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert body["instance"] == "/api/no-existe"


async def test_domain_problem() -> None:
    async with await _client(_app_with_test_routes()) as ac:
        response = await ac.get("/api/_test/problem")

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json()["detail"] == "Conflicto de prueba"
    assert response.json()["codigo"] == "X1"


async def test_validation_is_422_problem() -> None:
    async with await _client(_app_with_test_routes()) as ac:
        response = await ac.post("/api/_test/validate", json={"cantidad": "no-numero"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json()["errors"][0]["loc"] == ["body", "cantidad"]


async def test_unhandled_is_500_without_leaking() -> None:
    async with await _client(_app_with_test_routes()) as ac:
        response = await ac.get("/api/_test/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_JSON
    assert "fallo inesperado" not in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]
