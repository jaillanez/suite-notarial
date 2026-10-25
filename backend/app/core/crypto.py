"""Cifrado simétrico de secretos en reposo (AES-256-GCM)."""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12
_VERSION = "v1"


class DecryptionError(Exception):
    """El valor cifrado está corrupto o se cifró con otra clave."""


def encrypt_secret(plaintext: str, key: bytes, *, associated_data: bytes = b"") -> str:
    """Devuelve `v1.<base64(nonce + ciphertext)>`. El prefijo permite rotar el esquema."""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return f"{_VERSION}.{base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')}"


def decrypt_secret(token: str, key: bytes, *, associated_data: bytes = b"") -> str:
    version, _, payload = token.partition(".")
    if version != _VERSION or not payload:
        raise DecryptionError("Formato de secreto cifrado desconocido")
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        return AESGCM(key).decrypt(nonce, ciphertext, associated_data).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("No se pudo descifrar el secreto") from exc
