"""Valores de dominio de préstamos (Módulo 9)."""

from enum import StrEnum


class Sistema(StrEnum):
    """Francés: cuota constante. Alemán: amortización de capital constante, cuota decreciente."""

    FRANCES = "FRANCES"
    ALEMAN = "ALEMAN"


class EstadoPrestamo(StrEnum):
    SOLICITADO = "SOLICITADO"
    OTORGADO = "OTORGADO"
    RECHAZADO = "RECHAZADO"
    # Todas las cuotas pagadas.
    CANCELADO = "CANCELADO"


class EstadoCuota(StrEnum):
    PENDIENTE = "PENDIENTE"
    PAGADA = "PAGADA"
