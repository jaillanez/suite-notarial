"""Valores de dominio de comprobantes y conciliación (Módulo 6)."""

from enum import StrEnum


class EstadoComprobante(StrEnum):
    """Adjuntar un comprobante no es pagar (regla PAGO): solo Tesorería lo aprueba."""

    PENDIENTE_REVISION = "PENDIENTE_REVISION"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class ResultadoConciliacion(StrEnum):
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


# Tipo real detectado por magic bytes -> extensión con la que se guarda (regla MIME).
MIME_PERMITIDOS: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
