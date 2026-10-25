"""Avisos al escribano sobre su comprobante. Enlaces desde `PUBLIC_WEB_URL` (SEC-04)."""

from app.common.money import format_pesos
from app.core.config import Settings
from app.core.mail import OutgoingMail, render_mail
from app.modules.ddjj.models import Boleta
from app.modules.iam.models import User


def _contexto(settings: Settings, user: User, boleta: Boleta) -> dict[str, object]:
    return {
        "full_name": user.full_name,
        "numero": boleta.numero,
        "periodo": f"{boleta.periodo[5:7]}/{boleta.periodo[:4]}",
        "total": format_pesos(boleta.total_a_pagar),
        "link": f"{settings.public_web_base}/ddjj/{boleta.ddjj_id}",
    }


def comprobante_rechazado_mail(
    settings: Settings, user: User, boleta: Boleta, motivo: str
) -> OutgoingMail:
    return render_mail(
        "comprobante_rechazado",
        f"Comprobante rechazado · Boleta N° {boleta.numero}",
        user.email,
        {**_contexto(settings, user, boleta), "motivo": motivo},
    )


def comprobante_aprobado_mail(settings: Settings, user: User, boleta: Boleta) -> OutgoingMail:
    return render_mail(
        "comprobante_aprobado",
        f"Pago confirmado · Boleta N° {boleta.numero}",
        user.email,
        _contexto(settings, user, boleta),
    )
