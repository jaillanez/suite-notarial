"""TOTP (RFC 6238) con protección anti-replay y códigos de recuperación de un solo uso."""

import hashlib
import hmac
import io
import re
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg

STEP_SECONDS = 30
VALID_WINDOW = 1  # tolera ±30 s de desfase de reloj
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I/L
_CODE_RE = re.compile(r"^\d{6}$")


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def qr_svg(data: str) -> str:
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def verify_code(
    secret: str, code: str, *, last_used_step: int | None, now: float | None = None
) -> int | None:
    """Devuelve el paso aceptado, o `None` si el código es inválido o ya se usó."""
    code = code.strip().replace(" ", "")
    if not _CODE_RE.fullmatch(code):
        return None
    totp = pyotp.TOTP(secret)
    current_step = int((now if now is not None else time.time()) // STEP_SECONDS)
    for step in range(current_step - VALID_WINDOW, current_step + VALID_WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if secrets.compare_digest(totp.at(step * STEP_SECONDS), code):
            return step
    return None


RECOVERY_CODE_LENGTH = 12  # 32^12 = 60 bits por código
_RECOVERY_RE = re.compile(rf"^[{_RECOVERY_ALPHABET}]{{{RECOVERY_CODE_LENGTH}}}$")


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code).upper()


def looks_like_recovery_code(code: str) -> bool:
    return _RECOVERY_RE.fullmatch(normalize_recovery_code(code)) is not None


def generate_recovery_codes() -> list[str]:
    """Códigos `XXXX-XXXX-XXXX` (60 bits cada uno). Se muestran una sola vez."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def recovery_code_key(master_key: bytes) -> bytes:
    """Clave HMAC derivada (separada por dominio) de la clave de cifrado del servidor."""
    return hmac.new(master_key, b"suite-notarial:recovery-codes:v1", hashlib.sha256).digest()


def hash_recovery_code(code: str, *, key: bytes, user_id: str) -> str:
    """HMAC-SHA256 con clave del servidor, atado al usuario.

    Los códigos son 60 bits aleatorios: no hay diccionario que atacar, así que una función
    lenta no agrega seguridad y sí costo. Sin la clave del servidor, la base sola no sirve
    para probar códigos. La búsqueda queda en una sola comparación indexada.
    """
    message = f"{user_id}:{normalize_recovery_code(code)}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()
