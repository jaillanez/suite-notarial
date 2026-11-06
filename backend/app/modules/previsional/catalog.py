"""Valores de dominio de aportes y puntos previsionales (reglamentación de la Ley 7231)."""

from enum import StrEnum

# Escalas: aportes con 2 decimales (`to_money`), puntos y aporte medio con 6 (`to_points`) y la
# cantidad de afiliados con 4 (`to_rate`): en la planilla hay años estimados, no enteros.


class Vinculacion(StrEnum):
    """Por qué una fila de puntos es de un escribano (`escribano_id` cargado).

    Solo estas formas atribuyen puntos: alimentan el informe, el PDF, el portal y los reportes.
    Una coincidencia aproximada NO es un vínculo: queda como sugerencia
    (`escribano_sugerido_id`) hasta que una persona la confirme.
    """

    # El nombre normalizado coincide con el de un único escribano (automático, sin autor).
    EXACTA = "EXACTA"
    # Fila nueva de un nombre que una persona ya vinculó a mano en otro ejercicio. Cuenta para el
    # escribano (la decisión humana es sobre el nombre) pero no tiene autor: queda en la cola de
    # revisión para que la Caja la confirme en el ejercicio nuevo.
    HEREDADA = "HEREDADA"
    # Lo vinculó o confirmó una persona autorizada desde la Suite (siempre con autor, auditado).
    MANUAL = "MANUAL"


class Coincidencia(StrEnum):
    """Resultado de comparar un nombre de la planilla con el padrón."""

    EXACTA = "EXACTA"
    # Todas las palabras de la planilla en el nombre de un único escribano: solo una sugerencia.
    APROXIMADA = "APROXIMADA"


class EstadoVinculo(StrEnum):
    """Filtro de la cola de revisión «Puntos sin vincular»."""

    # Sin escribano ni sugerencia.
    SIN_VINCULAR = "SIN_VINCULAR"
    # Sin escribano, con una sugerencia aproximada para confirmar o rechazar.
    APROXIMADA = "APROXIMADA"
    # Vinculadas por herencia de una decisión manual: cuentan, pero falta confirmarlas.
    HEREDADA = "HEREDADA"


MOTIVO_SIN_REGLA = (
    "Falta la regla oficial de cálculo de la Caja (TODO(negocio)): los puntos de un ejercicio "
    "nuevo no se calculan hasta que la Caja apruebe la fórmula."
)
