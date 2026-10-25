import re
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sha256_hex
from app.modules.iam.models import PasswordResetToken
from app.modules.iam.service import INVALID_RESET_TOKEN, RESET_REQUEST_ACK
from tests.conftest import FakeMailer
from tests.iam.factories import PASSWORD, make_user
from tests.iam.test_rbac import login

NEW_PASSWORD = "Nueva-Clave-Segura-77!"
LINK_RE = re.compile(r"https://suite\.cajanotarial-sj\.test/restablecer-clave#token=([\w-]+)")


async def _request_token(client: AsyncClient, mailer: FakeMailer, identifier: str) -> str:
    await client.post("/api/v1/auth/password-reset/request", json={"identifier": identifier})
    match = LINK_RE.search(mailer.sent[-1].text)
    assert match is not None
    return match.group(1)


async def test_request_is_identical_for_unknown_accounts(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)

    known = await client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": user.email}
    )
    unknown = await client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": "nadie@suite-notarial.example"}
    )

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"message": RESET_REQUEST_ACK}
    assert [m.to for m in mailer.sent] == [user.email]


async def test_mail_link_uses_public_url_and_token_is_hashed(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)

    token = await _request_token(client, mailer, user.email)

    mail = mailer.sent[-1]
    assert "localhost" not in mail.text + mail.html
    assert f"#token={token}" in mail.html
    stored = (
        await db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
    ).scalar_one()
    assert stored.token_hash == sha256_hex(token)
    assert token not in stored.token_hash
    ttl = stored.expires_at - stored.created_at
    assert timedelta(minutes=29) < ttl <= timedelta(minutes=30, seconds=5)


async def test_token_is_single_use_and_revokes_sessions(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    await login(client, user)
    token = await _request_token(client, mailer, user.email)

    ok = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert ok.status_code == 200
    assert mailer.sent[-1].subject.startswith("Se cambió tu contraseña")
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    reused = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "Otra-Clave-Segura-88!"},
    )
    assert reused.status_code == 400
    assert reused.json()["detail"] == INVALID_RESET_TOKEN

    old = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    new = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": NEW_PASSWORD}
    )
    assert old.status_code == 401
    assert new.status_code == 200


async def test_expired_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    token = await _request_token(client, mailer, user.email)
    await db_session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400


async def test_weak_password_does_not_burn_token(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    token = await _request_token(client, mailer, user.email)

    weak = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "corta"}
    )
    assert weak.status_code == 422

    strong = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert strong.status_code == 200


async def test_new_request_invalidates_previous_token(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)
    first = await _request_token(client, mailer, user.email)
    await _request_token(client, mailer, user.email)

    response = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": first, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400


async def test_requests_are_rate_limited(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    user = await make_user(db_session)

    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/password-reset/request", json={"identifier": user.email}
        )
        assert response.json() == {"message": RESET_REQUEST_ACK}

    assert len(mailer.sent) == 3
