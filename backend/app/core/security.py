"""Primitivas de seguridad compartidas. La lógica de IAM completa llega en la Fase 1."""

import hashlib
import secrets


def generate_token(nbytes: int = 32) -> str:
    """Token aleatorio URL-safe criptográficamente seguro."""
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    """Hash SHA-256 en hex; se usa para persistir tokens de un solo uso sin guardarlos en claro."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
