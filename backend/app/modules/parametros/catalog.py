"""Tipos y estados del motor paramétrico."""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from enum import StrEnum


class TipoConcepto(StrEnum):
    # Porcentaje sobre la base imponible de cada escritura, con mínimo y tope opcionales.
    PORCENTUAL_ACTO = "PORCENTUAL_ACTO"
    # Monto fijo por cada acto (p. ej. actas y poderes, u otros actos sin base imponible).
    FIJO_ACTO = "FIJO_ACTO"
    # Monto fijo por período mensual (p. ej. aporte médico, aporte previsional mínimo).
    FIJO_MENSUAL = "FIJO_MENSUAL"
    # Tasa de interés mensual por mora, con días de gracia sobre el vencimiento.
    TASA_MORA = "TASA_MORA"
    # Regla (no un monto): cómo aportan varios actos de una misma escritura (`criterio`).
    CRITERIO_PLURALIDAD = "CRITERIO_PLURALIDAD"


class CriterioPluralidad(StrEnum):
    """Cómo aportan los actos de una escritura con varios actos y las mismas partes.

    Con partes distintas aporta cada acto (vademécum de la Caja, nota «pluralidad de actos y de
    partes»). Es una política de la Caja: se cambia con una vigencia nueva, sin tocar el código.
    """

    # Aporta solo el acto que más aporta (vademécum 2026, nota «pluralidad de actos»).
    SOLO_EL_MAYOR = "SOLO_EL_MAYOR"
    # Aporta cada acto.
    SUMAN_TODOS = "SUMAN_TODOS"
    # Los actos de aporte variable aportan cada uno; de los de monto fijo, solo el mayor.
    VARIABLES_SUMAN_FIJO_UNA_VEZ = "VARIABLES_SUMAN_FIJO_UNA_VEZ"


class PeriodoTasa(StrEnum):
    """Unidad en que se expresa la tasa de mora."""

    MENSUAL = "MENSUAL"
    ANUAL = "ANUAL"


class EstadoVigencia(StrEnum):
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION"
    VIGENTE = "VIGENTE"
    RECHAZADA = "RECHAZADA"
    # Quien la propuso (u otra persona que puede proponer) la retiró antes de que se aprobara,
    # para descartarla o para reemplazarla por una corregida.
    RETIRADA = "RETIRADA"


class ReglaRedondeo(StrEnum):
    HALF_UP = "HALF_UP"
    FLOOR = "FLOOR"
    CEILING = "CEILING"


ROUNDING_MODES: dict[ReglaRedondeo, str] = {
    ReglaRedondeo.HALF_UP: ROUND_HALF_UP,
    ReglaRedondeo.FLOOR: ROUND_FLOOR,
    ReglaRedondeo.CEILING: ROUND_CEILING,
}
