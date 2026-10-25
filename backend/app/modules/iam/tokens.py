"""JWT de acceso y de desafío 2FA (HS256)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import Settings

ISSUER = "suite-notarial"
AUDIENCE = "suite-notarial-api"
ALGORITHM = "HS256"

TokenType = Literal["access", "mfa_pending"]


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    mfa: bool


@dataclass(frozen=True)
class MfaPendingClaims:
    user_id: uuid.UUID


def _encode(settings: Settings, payload: dict[str, object], ttl: timedelta) -> str:
    now = datetime.now(UTC)
    claims = {
        **payload,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM)


def _decode(settings: Settings, token: str, expected: TokenType) -> dict[str, object]:
    try:
        claims: dict[str, object] = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "sub", "typ", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if claims.get("typ") != expected:
        raise InvalidTokenError("Tipo de token inesperado")
    return claims


def _uuid_claim(claims: dict[str, object], name: str) -> uuid.UUID:
    value = claims.get(name)
    if not isinstance(value, str):
        raise InvalidTokenError(f"Claim {name} ausente")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidTokenError(f"Claim {name} inválido") from exc


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, session_id: uuid.UUID, mfa: bool
) -> str:
    return _encode(
        settings,
        {"sub": str(user_id), "sid": str(session_id), "mfa": mfa, "typ": "access"},
        timedelta(minutes=settings.JWT_ACCESS_TTL_MIN),
    )


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    claims = _decode(settings, token, "access")
    return AccessClaims(
        user_id=_uuid_claim(claims, "sub"),
        session_id=_uuid_claim(claims, "sid"),
        mfa=claims.get("mfa") is True,
    )


def create_mfa_pending_token(settings: Settings, *, user_id: uuid.UUID) -> str:
    return _encode(
        settings,
        {"sub": str(user_id), "typ": "mfa_pending"},
        timedelta(minutes=settings.MFA_PENDING_TTL_MIN),
    )


def decode_mfa_pending_token(settings: Settings, token: str) -> MfaPendingClaims:
    return MfaPendingClaims(user_id=_uuid_claim(_decode(settings, token, "mfa_pending"), "sub"))
