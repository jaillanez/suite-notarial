from collections.abc import AsyncIterator
from datetime import datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_session
from app.main import create_app


async def test_health_db_up(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "up"
    assert datetime.fromisoformat(body["time_utc"]).utcoffset() is not None


class _BrokenSession:
    async def execute(self, *_: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("conexión rechazada"))


async def test_health_db_down() -> None:
    app = create_app()

    async def broken_session() -> AsyncIterator[_BrokenSession]:
        yield _BrokenSession()

    app.dependency_overrides[get_session] = broken_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")

    assert response.status_code == 200
    assert response.json()["db"] == "down"
    assert response.json()["status"] == "degraded"
