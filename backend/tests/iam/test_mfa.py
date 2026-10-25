import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.deps import MFA_ENROLLMENT_TYPE
from app.modules.iam.models import RecoveryCode, User
from app.modules.iam.service import INVALID_MFA
from tests.iam.factories import PASSWORD, make_user, totp_code


async def _password_step(client: AsyncClient, user: User) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/login", json={"identifier": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


async def test_password_alone_does_not_open_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, totp_secret=secret)

    body = await _password_step(client, user)

    assert body["status"] == "mfa_required"
    assert "sn_access" not in client.cookies
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_totp_completes_login_and_blocks_replay(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, totp_secret=secret)
    code = totp_code(secret)

    await _password_step(client, user)
    ok = await client.post("/api/v1/auth/login/mfa", json={"code": code})
    assert ok.status_code == 200
    assert ok.json()["user"]["mfa_verified"] is True

    await _password_step(client, user)
    replay = await client.post("/api/v1/auth/login/mfa", json={"code": code})
    assert replay.status_code == 401
    assert replay.json()["detail"] == INVALID_MFA


async def test_mfa_step_requires_password_step(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    secret = pyotp.random_base32()
    await make_user(db_session, totp_secret=secret)

    response = await client.post("/api/v1/auth/login/mfa", json={"code": totp_code(secret)})

    assert response.status_code == 401


async def test_wrong_codes_lock_account(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, totp_secret=secret)

    await _password_step(client, user)
    for _ in range(5):
        await client.post("/api/v1/auth/login/mfa", json={"code": "000000"})
    blocked = await client.post("/api/v1/auth/login/mfa", json={"code": totp_code(secret)})

    assert blocked.status_code == 401
    await db_session.refresh(user)
    assert user.locked_until is not None


async def test_enrollment_enables_mfa_with_recovery_codes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await _password_step(client, user)

    setup = await client.post("/api/v1/auth/mfa/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert setup.json()["qr_svg"].lstrip().startswith("<?xml")

    await db_session.refresh(user)
    assert user.totp_secret_encrypted is not None
    assert secret not in user.totp_secret_encrypted

    enabled = await client.post("/api/v1/auth/mfa/enable", json={"code": totp_code(secret)})
    assert enabled.status_code == 200
    codes = enabled.json()["recovery_codes"]
    assert len(codes) == 10
    assert len(set(codes)) == 10

    me = await client.get("/api/v1/auth/me")
    assert me.json()["mfa_enabled"] is True
    assert me.json()["mfa_verified"] is True

    stored = list(
        (
            await db_session.execute(
                select(RecoveryCode.code_hash).where(RecoveryCode.user_id == user.id)
            )
        ).scalars()
    )
    assert len(stored) == 10
    assert all(h.startswith("$argon2id$") for h in stored)


async def test_recovery_code_is_single_use(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _password_step(client, user)
    secret = (await client.post("/api/v1/auth/mfa/setup")).json()["secret"]
    codes = (await client.post("/api/v1/auth/mfa/enable", json={"code": totp_code(secret)})).json()[
        "recovery_codes"
    ]
    await client.post("/api/v1/auth/logout")

    await _password_step(client, user)
    first = await client.post("/api/v1/auth/login/mfa", json={"code": codes[0].lower()})
    assert first.status_code == 200
    await client.post("/api/v1/auth/logout")

    await _password_step(client, user)
    second = await client.post("/api/v1/auth/login/mfa", json={"code": codes[0]})
    assert second.status_code == 401


async def test_privileged_role_must_enroll_before_acting(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await make_user(db_session, roles=("ROLE_ADMIN",))
    login = await _password_step(client, admin)
    assert login["status"] == "authenticated"

    blocked = await client.get("/api/v1/users")
    assert blocked.status_code == 403
    assert blocked.json()["type"] == MFA_ENROLLMENT_TYPE

    secret = (await client.post("/api/v1/auth/mfa/setup")).json()["secret"]
    await client.post("/api/v1/auth/mfa/enable", json={"code": totp_code(secret)})

    allowed = await client.get("/api/v1/users")
    assert allowed.status_code == 200


async def test_privileged_role_cannot_disable_mfa(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    secret = pyotp.random_base32()
    admin = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    await _password_step(client, admin)
    await client.post("/api/v1/auth/login/mfa", json={"code": totp_code(secret)})

    response = await client.post(
        "/api/v1/auth/mfa/disable", json={"password": PASSWORD, "code": totp_code(secret, 1)}
    )

    assert response.status_code == 403


async def test_escribano_can_disable_mfa(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, totp_secret=secret)
    await _password_step(client, user)
    await client.post("/api/v1/auth/login/mfa", json={"code": totp_code(secret)})

    wrong_password = await client.post(
        "/api/v1/auth/mfa/disable",
        json={"password": "Otra-Clave-123!", "code": totp_code(secret, 1)},
    )
    assert wrong_password.status_code == 422

    response = await client.post(
        "/api/v1/auth/mfa/disable", json={"password": PASSWORD, "code": totp_code(secret, 1)}
    )
    assert response.status_code == 200
    await db_session.refresh(user)
    assert user.totp_enabled is False
    assert user.totp_secret_encrypted is None
