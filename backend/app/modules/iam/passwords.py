"""Hash de contraseñas con Argon2id y política de complejidad."""

import asyncio
import re
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
MAX_LENGTH = 128

_hasher = PasswordHasher()  # Argon2id con los parámetros recomendados por argon2-cffi (RFC 9106)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("contraseña-ficticia-para-igualar-tiempos")


def burn_verification_time(password: str) -> None:
    """Verifica contra un hash ficticio: un usuario inexistente tarda igual (anti-enumeración)."""
    verify_password(_dummy_hash(), password)


# Argon2id es CPU intensivo a propósito: en el camino async corre en un hilo para no frenar
# el event loop (y con él, a todos los demás usuarios).


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(hashed: str, password: str) -> bool:
    return await asyncio.to_thread(verify_password, hashed, password)


async def burn_verification_time_async(password: str) -> None:
    await asyncio.to_thread(burn_verification_time, password)


class WeakPasswordError(ValueError):
    pass


def check_password_policy(password: str, *, email: str | None = None) -> None:
    """Política de la Caja (Módulo 2 §6): longitud mínima y las cuatro clases de caracteres."""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"al menos {MIN_LENGTH} caracteres")
    if len(password) > MAX_LENGTH:
        problems.append(f"como máximo {MAX_LENGTH} caracteres")
    if not re.search(r"[A-ZÁÉÍÓÚÑ]", password):
        problems.append("una letra mayúscula")
    if not re.search(r"[a-záéíóúñ]", password):
        problems.append("una letra minúscula")
    if not re.search(r"[0-9]", password):
        problems.append("un número")
    if not re.search(r"[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ]", password):
        problems.append("un carácter especial")
    contains_email = False
    if email:
        local = email.split("@", 1)[0].lower()
        contains_email = len(local) >= 4 and local in password.lower()
    messages: list[str] = []
    if problems:
        messages.append("La contraseña debe tener " + ", ".join(problems) + ".")
    if contains_email:
        messages.append("La contraseña no puede contener tu usuario de correo.")
    if messages:
        raise WeakPasswordError(" ".join(messages))
