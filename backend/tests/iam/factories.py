"""Fábricas de datos sintéticos para los tests de IAM."""

import time
import uuid
from itertools import count

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.cuit import check_digit
from app.core.config import get_settings
from app.core.crypto import encrypt_secret
from app.modules.iam import passwords
from app.modules.iam.models import Role, User, UserRole

PASSWORD = "Prueba-Segura-2026!"
_seq = count(1)


def synthetic_cuit() -> str:
    while True:
        body = f"20{next(_seq) + 40_000_000:08d}"
        digit = check_digit(body)
        if digit is not None:
            return body + str(digit)


async def make_user(
    session: AsyncSession,
    *,
    roles: tuple[str, ...] = ("ROLE_ESCRIBANO",),
    password: str = PASSWORD,
    totp_secret: str | None = None,
    is_active: bool = True,
    email: str | None = None,
) -> User:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=email or f"u{user_id.hex[:10]}@suite-notarial.example",
        cuit=synthetic_cuit(),
        full_name="Usuario de Prueba",
        hashed_password=passwords.hash_password(password),
        is_active=is_active,
        is_verified=True,
    )
    if totp_secret:
        user.totp_enabled = True
        user.totp_secret_encrypted = encrypt_secret(
            totp_secret,
            get_settings().data_encryption_key,
            associated_data=f"totp:{user_id}".encode(),
        )
    session.add(user)
    await session.flush()
    for code in roles:
        role = (await session.execute(select(Role).where(Role.code == code))).scalar_one()
        session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    await session.refresh(user, attribute_names=["roles"])
    return user


def totp_code(secret: str, step_offset: int = 0) -> str:
    """Código TOTP del paso actual desplazado; los tests usan pasos distintos para no chocar
    con la protección anti-replay."""
    return pyotp.TOTP(secret).at(int(time.time()) + step_offset * 30)


def replace_cookie(client: AsyncClient, name: str, value: str, path: str) -> None:
    """Reemplaza la cookie como lo haría un atacante con un valor robado o falsificado.

    httpx guarda las cookies de `https://test` bajo el dominio `test.local`: hay que borrar
    la existente para no enviar dos con el mismo nombre.
    """
    for cookie in list(client.cookies.jar):
        if cookie.name == name:
            client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    client.cookies.set(name, value, domain="test.local", path=path)
