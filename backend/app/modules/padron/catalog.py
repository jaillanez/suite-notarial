"""Valores de dominio del padrón notarial."""

from enum import StrEnum


class EstadoMatricula(StrEnum):
    ACTIVO = "ACTIVO"
    SUSPENDIDO = "SUSPENDIDO"
    CESANTE = "CESANTE"
    JUBILADO = "JUBILADO"
    FALLECIDO = "FALLECIDO"


# Estados que terminan el ejercicio: exigen que no queden cargos vigentes en registros y
# suspenden la cuenta de autogestión.
ESTADOS_DEFINITIVOS = frozenset(
    {EstadoMatricula.CESANTE, EstadoMatricula.JUBILADO, EstadoMatricula.FALLECIDO}
)
ESTADOS_TERMINALES = frozenset({EstadoMatricula.FALLECIDO})

_E = EstadoMatricula
# Transiciones permitidas. Criterio:
# - La suspensión es temporal: termina (vuelve a ACTIVO) o deriva en una baja.
# - Un cesante puede reincorporarse, pero solo con resolución (ver REQUIERE_RESOLUCION).
# - Un jubilado no vuelve a ejercer por cambio de estado: requiere un trámite nuevo.
# - FALLECIDO es terminal.
TRANSICIONES: dict[EstadoMatricula, frozenset[EstadoMatricula]] = {
    _E.ACTIVO: frozenset({_E.SUSPENDIDO, _E.CESANTE, _E.JUBILADO, _E.FALLECIDO}),
    _E.SUSPENDIDO: frozenset({_E.ACTIVO, _E.CESANTE, _E.JUBILADO, _E.FALLECIDO}),
    _E.CESANTE: frozenset({_E.ACTIVO, _E.JUBILADO, _E.FALLECIDO}),
    _E.JUBILADO: frozenset({_E.FALLECIDO}),
    _E.FALLECIDO: frozenset(),
}
# Transiciones que solo proceden con un acto formal citado.
REQUIERE_RESOLUCION: frozenset[tuple[EstadoMatricula, EstadoMatricula]] = frozenset(
    {(_E.CESANTE, _E.ACTIVO)}
)


class Cargo(StrEnum):
    TITULAR = "TITULAR"
    ADSCRIPTO = "ADSCRIPTO"
    SUPLENTE_INTERINO = "SUPLENTE_INTERINO"


class EstadoRegistro(StrEnum):
    ACTIVO = "ACTIVO"
    VACANTE = "VACANTE"
    CERRADO = "CERRADO"


class TipoDocumento(StrEnum):
    DNI = "DNI"
    LC = "LC"
    LE = "LE"
    PASAPORTE = "PASAPORTE"


# Los 19 departamentos de la Provincia de San Juan.
DEPARTAMENTOS_SAN_JUAN: tuple[str, ...] = (
    "Albardón",
    "Angaco",
    "Calingasta",
    "Capital",
    "Caucete",
    "Chimbas",
    "Iglesia",
    "Jáchal",
    "9 de Julio",
    "Pocito",
    "Rawson",
    "Rivadavia",
    "San Martín",
    "Santa Lucía",
    "Sarmiento",
    "Ullum",
    "Valle Fértil",
    "25 de Mayo",
    "Zonda",
)
