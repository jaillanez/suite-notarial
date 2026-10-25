import pytest

from app.core.config import Environment, Settings
from app.core.mail import InvalidMailError, OutgoingMail


@pytest.mark.parametrize(
    "to",
    [
        "victima@example.com\r\nBcc: atacante@example.com",
        "a@example.com, b@example.com",
        "Nombre <a@example.com>",
        "sin-arroba",
        "a@example.com\0",
    ],
)
def test_rejects_header_injection_in_recipient(to: str) -> None:
    with pytest.raises(InvalidMailError):
        OutgoingMail(to=to, subject="Asunto", text="t", html="h")


def test_rejects_header_injection_in_subject() -> None:
    with pytest.raises(InvalidMailError):
        OutgoingMail(to="a@example.com", subject="Hola\r\nBcc: x@example.com", text="t", html="h")


def test_accepts_single_plain_address() -> None:
    mail = OutgoingMail(to="escribano@example.com", subject="Asunto", text="t", html="h")
    assert mail.to == "escribano@example.com"


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_smtp_without_tls_rejected_outside_dev(env: Environment) -> None:
    with pytest.raises(ValueError, match="SMTP_SECURITY"):
        Settings(
            ENVIRONMENT=env,
            PUBLIC_WEB_URL="https://suite.cajanotarial-sj.com.ar",
            SMTP_SECURITY="none",
        )
