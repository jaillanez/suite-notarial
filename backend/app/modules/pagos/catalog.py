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


class OrigenComprobante(StrEnum):
    ARCHIVO = "ARCHIVO"  # el escribano adjunta el comprobante de una transferencia
    MERCADO_PAGO = "MERCADO_PAGO"  # Mercado Pago informó el pago aprobado


class EstadoPagoMP(StrEnum):
    """Estado del pago según Mercado Pago (más CREADO: el cobro se armó y no hay pago todavía)."""

    CREADO = "CREADO"
    PENDING = "pending"
    AUTHORIZED = "authorized"
    IN_PROCESS = "in_process"
    IN_MEDIATION = "in_mediation"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    CHARGED_BACK = "charged_back"


# Un pago aprobado que después se devuelve o se desconoce: Tesorería tiene que saberlo.
ESTADOS_MP_REVERTIDOS = frozenset({EstadoPagoMP.REFUNDED, EstadoPagoMP.CHARGED_BACK})
