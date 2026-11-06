"""Valores de dominio de aportes y puntos previsionales (reglamentación de la Ley 7231)."""

from enum import StrEnum

# Escalas: aportes con 2 decimales (`to_money`), puntos y aporte medio con 6 (`to_points`) y la
# cantidad de afiliados con 4 (`to_rate`): en la planilla hay años estimados, no enteros.


class Vinculacion(StrEnum):
    """Cómo quedó asociado un nombre de la planilla a un escribano del padrón."""

    # El nombre normalizado coincide con el de un único escribano.
    EXACTA = "EXACTA"
    # Todas las palabras del nombre de la planilla están en el de un único escribano: queda
    # vinculado, pero listado para que alguien lo revise y lo confirme.
    APROXIMADA = "APROXIMADA"
    # Lo vinculó (o confirmó) una persona autorizada desde la Suite; queda auditado.
    MANUAL = "MANUAL"


class EstadoVinculo(StrEnum):
    """Filtro de la lista «Puntos sin vincular»."""

    SIN_VINCULAR = "SIN_VINCULAR"
    APROXIMADA = "APROXIMADA"


MOTIVO_SIN_REGLA = (
    "Falta la regla oficial de cálculo de la Caja (TODO(negocio)): los puntos de un ejercicio "
    "nuevo no se calculan hasta que la Caja apruebe la fórmula."
)
