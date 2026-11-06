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


class Moneda(StrEnum):
    """Moneda de una línea y de sus préstamos: capital, cuotas e ingreso van en la misma.

    Nunca se suman importes de monedas distintas.
    """

    ARS = "ARS"
    USD = "USD"


SIMBOLO_MONEDA: dict[Moneda, str] = {Moneda.ARS: "$", Moneda.USD: "US$"}

# TODO(negocio): definir tipo de cambio para evaluar la afectación de préstamos en dólares.
# Mientras tanto, en un préstamo en dólares el ingreso neto se declara en dólares y la
# afectación solo suma cuotas de préstamos en la misma moneda.
AVISO_TIPO_CAMBIO = (
    "Préstamo en dólares: el ingreso neto se declara en dólares. La Caja todavía no definió "
    "el tipo de cambio para evaluar la afectación con ingresos o préstamos en pesos."
)
