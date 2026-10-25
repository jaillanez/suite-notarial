"""Envío de correo con plantillas Jinja2. En desarrollo el SMTP es Mailpit.

Las plantillas reciben `public_web_url` y nunca construyen enlaces con otro host (SEC-04).
"""

import logging
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Protocol

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "mail"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


_FORBIDDEN_HEADER_CHARS = ("\r", "\n", "\0")


class InvalidMailError(ValueError):
    """Destinatario o asunto que podría inyectar cabeceras o ampliar el sobre SMTP."""


def _single_address(value: str) -> str:
    if any(c in value for c in _FORBIDDEN_HEADER_CHARS):
        raise InvalidMailError("Dirección con caracteres de control")
    parsed = getaddresses([value])
    if len(parsed) != 1 or not parsed[0][1] or parsed[0][1] != value.strip():
        raise InvalidMailError("Se esperaba exactamente una dirección de correo")
    username, sep, domain = parsed[0][1].rpartition("@")
    if not sep or not username or not domain:
        raise InvalidMailError("Dirección de correo inválida")
    return str(Address(username=username, domain=domain))


@dataclass(frozen=True)
class OutgoingMail:
    to: str
    subject: str
    text: str
    html: str

    def __post_init__(self) -> None:
        _single_address(self.to)
        if any(c in self.subject for c in _FORBIDDEN_HEADER_CHARS):
            raise InvalidMailError("Asunto con caracteres de control")


def render_mail(template: str, subject: str, to: str, context: dict[str, Any]) -> OutgoingMail:
    """Renderiza `<template>.txt` y `<template>.html`."""
    full_context = {**context, "subject": subject}
    return OutgoingMail(
        to=to,
        subject=subject,
        text=_env.get_template(f"{template}.txt").render(**full_context),
        html=_env.get_template(f"{template}.html").render(**full_context),
    )


class Mailer(Protocol):
    async def send(self, mail: OutgoingMail) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, mail: OutgoingMail) -> None:
        settings = self._settings
        recipient = _single_address(mail.to)
        sender = _single_address(settings.MAIL_FROM)
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = mail.subject
        message.set_content(mail.text)
        message.add_alternative(mail.html, subtype="html")
        # El sobre se fija explícitamente: las cabeceras nunca pueden agregar destinatarios.
        await aiosmtplib.send(
            message,
            sender=sender,
            recipients=[recipient],
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            use_tls=settings.SMTP_SECURITY == "tls",
            start_tls=settings.SMTP_SECURITY == "starttls",
            validate_certs=True,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD.get_secret_value() if settings.SMTP_PASSWORD else None,
            timeout=15,
        )


async def send_safely(mailer: Mailer, mail: OutgoingMail) -> None:
    """Envía sin propagar errores: corre en segundo plano, donde nadie puede reintentar."""
    try:
        await mailer.send(mail)
    except (aiosmtplib.SMTPException, OSError):
        logger.exception("No se pudo enviar el correo", extra={"subject": mail.subject})
