"""Envío de correo con plantillas Jinja2. En desarrollo el SMTP es Mailpit.

Las plantillas reciben `public_web_url` y nunca construyen enlaces con otro host (SEC-04).
"""

import logging
from dataclasses import dataclass
from email.message import EmailMessage
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


@dataclass(frozen=True)
class OutgoingMail:
    to: str
    subject: str
    text: str
    html: str


def render_mail(template: str, subject: str, to: str, context: dict[str, Any]) -> OutgoingMail:
    """Renderiza `<template>.txt` y `<template>.html`."""
    return OutgoingMail(
        to=to,
        subject=subject,
        text=_env.get_template(f"{template}.txt").render(**context),
        html=_env.get_template(f"{template}.html").render(**context),
    )


class Mailer(Protocol):
    async def send(self, mail: OutgoingMail) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, mail: OutgoingMail) -> None:
        message = EmailMessage()
        message["From"] = self._settings.MAIL_FROM
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message.set_content(mail.text)
        message.add_alternative(mail.html, subtype="html")
        await aiosmtplib.send(
            message,
            hostname=self._settings.SMTP_HOST,
            port=self._settings.SMTP_PORT,
            timeout=15,
        )


async def send_safely(mailer: Mailer, mail: OutgoingMail) -> None:
    """Envía sin propagar errores: corre en segundo plano, donde nadie puede reintentar."""
    try:
        await mailer.send(mail)
    except (aiosmtplib.SMTPException, OSError):
        logger.exception("No se pudo enviar el correo", extra={"subject": mail.subject})
