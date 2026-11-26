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
    SUPERVIELLE = "SUPERVIELLE"  # el botón de pagos Supervielle informó el pago aprobado


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


class EstadoPagoSPV(StrEnum):
    """Estado del pago según el botón Supervielle (tabla «Estados de Pago» de la API), más
    CREADO: la deuda se publicó y no hay pago todavía."""

    CREADO = "CREADO"
    APROBADO = "APROBADO"
    ACREDITADO = "ACREDITADO"
    PENDIENTE = "PENDIENTE"
    REVERSADO = "REVERSADO"
    ANULADO = "ANULADO"


# `id_estado_pago` de la API -> estado. Un id desconocido se toma como PENDIENTE.
ESTADOS_SPV: dict[int, EstadoPagoSPV] = {
    1: EstadoPagoSPV.APROBADO,
    2: EstadoPagoSPV.ACREDITADO,
    3: EstadoPagoSPV.PENDIENTE,
    4: EstadoPagoSPV.REVERSADO,
    5: EstadoPagoSPV.ANULADO,
}
# Pago hecho: genera el comprobante para Tesorería.
ESTADOS_SPV_EFECTIVOS = frozenset({EstadoPagoSPV.APROBADO, EstadoPagoSPV.ACREDITADO})
# Un pago hecho que después se reversa o se anula: Tesorería tiene que saberlo.
ESTADOS_SPV_REVERTIDOS = frozenset({EstadoPagoSPV.REVERSADO, EstadoPagoSPV.ANULADO})

# `id_medio_pago` de la API -> medio, en palabras.
MEDIOS_SPV: dict[int, str] = {
    1: "Tarjeta de crédito",
    2: "Tarjeta de débito",
    3: "Caja en banco Supervielle",
    4: "QR MODO",
    5: "Debin",
}


class TipoAjuste(StrEnum):
    """Un crédito baja lo que se debe de la boleta; un débito lo sube (Caja, 26/11/2026)."""

    CREDITO = "CREDITO"
    DEBITO = "DEBITO"


class ConceptoAjuste(StrEnum):
    # Centavos de más o de menos al pagar.
    REDONDEO = "REDONDEO"
    # Rebaja de intereses resuelta por la Junta.
    REDUCCION_INTERESES = "REDUCCION_INTERESES"
    # Condonación total o parcial resuelta por la Junta (p. ej., escribano que no trabaja).
    CONDONACION = "CONDONACION"
    # Diferencia de una DDJJ rectificativa.
    DIFERENCIA_RECTIFICATIVA = "DIFERENCIA_RECTIFICATIVA"
    OTRO = "OTRO"


# Los que dispone la Junta llevan la resolución que los respalda.
CONCEPTOS_CON_RESOLUCION: frozenset[ConceptoAjuste] = frozenset(
    {ConceptoAjuste.REDUCCION_INTERESES, ConceptoAjuste.CONDONACION}
)


class EstadoAjuste(StrEnum):
    PROPUESTO = "PROPUESTO"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
