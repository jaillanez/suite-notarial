import time

import pyotp
import pytest

from app.core.crypto import DecryptionError, decrypt_secret, encrypt_secret
from app.modules.iam import totp

KEY = bytes(range(32))


def test_encrypt_roundtrip_and_nonce_uniqueness() -> None:
    first = encrypt_secret("semilla", KEY, associated_data=b"u1")
    second = encrypt_secret("semilla", KEY, associated_data=b"u1")

    assert first != second
    assert "semilla" not in first
    assert decrypt_secret(first, KEY, associated_data=b"u1") == "semilla"


def test_ciphertext_bound_to_user_and_key() -> None:
    token = encrypt_secret("semilla", KEY, associated_data=b"u1")

    with pytest.raises(DecryptionError):
        decrypt_secret(token, KEY, associated_data=b"u2")
    with pytest.raises(DecryptionError):
        decrypt_secret(token, bytes(32), associated_data=b"u1")


def test_totp_window_and_replay() -> None:
    secret = pyotp.random_base32()
    now = int(time.time())
    code = pyotp.TOTP(secret).at(now)

    step = totp.verify_code(secret, code, last_used_step=None, now=now)
    assert step is not None
    assert totp.verify_code(secret, code, last_used_step=step, now=now) is None
    previous = pyotp.TOTP(secret).at(now - 30)
    assert totp.verify_code(secret, previous, last_used_step=None, now=now) is not None
    stale = pyotp.TOTP(secret).at(now - 120)
    assert totp.verify_code(secret, stale, last_used_step=None, now=now) is None
    assert totp.verify_code(secret, "12ab56", last_used_step=None, now=now) is None


def test_recovery_codes_format_and_hashing() -> None:
    codes = totp.generate_recovery_codes()
    key = totp.recovery_code_key(KEY)

    assert len(codes) == 10
    assert all(len(c) == 14 and c[4] == "-" and c[9] == "-" for c in codes)
    hashed = totp.hash_recovery_code(codes[0], key=key, user_id="u1")
    assert len(hashed) == 64
    assert hashed == totp.hash_recovery_code(
        codes[0].lower().replace("-", " "), key=key, user_id="u1"
    )
    assert hashed != totp.hash_recovery_code(codes[0], key=key, user_id="u2")
    assert hashed != totp.hash_recovery_code(
        codes[0], key=totp.recovery_code_key(bytes(32)), user_id="u1"
    )
    assert not totp.looks_like_recovery_code("1234-5678")
