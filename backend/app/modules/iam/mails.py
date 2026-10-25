"""Correos del módulo IAM. Todo enlace se arma desde `PUBLIC_WEB_URL` (SEC-04)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.mail import OutgoingMail, render_mail
from app.modules.iam.models import User
from app.modules.iam.service import reset_link

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


def password_changed_mail(settings: Settings, user: User, changed_at: datetime) -> OutgoingMail:
    return render_mail(
        "password_changed",
        "Se cambió tu contraseña · Suite Notarial",
        user.email,
        {
            "full_name": user.full_name,
            "changed_at": changed_at.astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M"),
            "link": f"{settings.public_web_base}/ingresar",
        },
    )
