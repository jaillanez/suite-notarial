"""Valores de dominio del padrón notarial."""

from enum import StrEnum


class EstadoMatricula(StrEnum):
    ACTIVO = "ACTIVO"
    SUSPENDIDO = "SUSPENDIDO"
    CESANTE = "CESANTE"
    JUBILADO = "JUBILADO"
    FALLECIDO = "FALLECIDO"


# Estados que terminan el ejercicio: exigen que no queden cargos vigentes en registros.
# TODO(negocio): confirmar con la Caja qué transiciones están permitidas entre estados.
ESTADOS_DEFINITIVOS = frozenset(
    {EstadoMatricula.CESANTE, EstadoMatricula.JUBILADO, EstadoMatricula.FALLECIDO}
)
ESTADOS_TERMINALES = frozenset({EstadoMatricula.FALLECIDO})


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
