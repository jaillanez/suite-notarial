"""Correos del módulo IAM. Todo enlace se arma desde `PUBLIC_WEB_URL` (SEC-04)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.mail import OutgoingMail, render_mail
from app.modules.iam.models import User
from app.modules.iam.service import EMAIL_CHANGE_TTL_MIN, email_change_link, reset_link

LOCAL_TZ = ZoneInfo("America/Argentina/San_Juan")


def password_reset_mail(settings: Settings, user: User, raw_token: str) -> OutgoingMail:
    return render_mail(
        "password_reset",
        "Restablecer tu contraseña · Suite Notarial",
        user.email,
        {
            "full_name": user.full_name,
            "link": reset_link(settings, raw_token),
            "ttl_minutes": settings.PASSWORD_RESET_TTL_MIN,
        },
    )


def account_created_mail(settings: Settings, user: User, raw_token: str) -> OutgoingMail:
    return render_mail(
        "account_created",
        "Tu cuenta en la Suite Notarial",
        user.email,
        {
            "full_name": user.full_name,
            "link": reset_link(settings, raw_token),
            "ttl_minutes": settings.PASSWORD_RESET_TTL_MIN,
        },
    )


def password_changed_mail(
    settings: Settings, user: User, changed_at: datetime, *, desde_la_cuenta: bool = False
) -> OutgoingMail:
    """Aviso de cambio de contraseña: por recuperación (se cierran todas las sesiones) o desde
    la cuenta (se cierran las demás)."""
    return render_mail(
        "password_changed",
        "Se cambió tu contraseña · Suite Notarial",
        user.email,
        {
            "full_name": user.full_name,
            "changed_at": changed_at.astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M"),
            "link": f"{settings.public_web_base}/ingresar",
            "desde_la_cuenta": desde_la_cuenta,
        },
    )


def email_change_mail(
    settings: Settings, user: User, nuevo_email: str, raw_token: str
) -> OutgoingMail:
    """Va a la dirección nueva: confirmarla prueba que es de quien pidió el cambio."""
    return render_mail(
        "email_change",
        "Confirmá tu nuevo correo · Suite Notarial",
        nuevo_email,
        {
            "full_name": user.full_name,
            "link": email_change_link(settings, raw_token),
            "ttl_minutes": EMAIL_CHANGE_TTL_MIN,
        },
    )


def email_changed_mail(settings: Settings, user: User, anterior: str) -> OutgoingMail:
    """Aviso a la dirección anterior: si no fue la persona, que avise a la Caja."""
    return render_mail(
        "email_changed",
        "Se cambió el correo de tu cuenta · Suite Notarial",
        anterior,
        {
            "full_name": user.full_name,
            "nuevo_email": user.email,
            "link": f"{settings.public_web_base}/ingresar",
        },
    )
