"""Tipos y estados del motor paramétrico."""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from enum import StrEnum


class TipoConcepto(StrEnum):
    # Porcentaje sobre la base imponible de cada escritura, con mínimo y tope opcionales.
    PORCENTUAL_ACTO = "PORCENTUAL_ACTO"
    # Monto fijo por período mensual.
    FIJO_MENSUAL = "FIJO_MENSUAL"
    # Tasa de interés mensual por mora, con días de gracia sobre el vencimiento.
    TASA_MORA = "TASA_MORA"


class EstadoVigencia(StrEnum):
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION"
    VIGENTE = "VIGENTE"
    RECHAZADA = "RECHAZADA"


class ReglaRedondeo(StrEnum):
    HALF_UP = "HALF_UP"
    FLOOR = "FLOOR"
    CEILING = "CEILING"


ROUNDING_MODES: dict[ReglaRedondeo, str] = {
    ReglaRedondeo.HALF_UP: ROUND_HALF_UP,
    ReglaRedondeo.FLOOR: ROUND_FLOOR,
    ReglaRedondeo.CEILING: ROUND_CEILING,
}
