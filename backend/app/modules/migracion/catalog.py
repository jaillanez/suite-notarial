from enum import StrEnum


class Entidad(StrEnum):
    """Archivos del formato de intercambio, en orden de carga (cada uno depende de los previos)."""

    REGISTROS = "registros"
    ESCRIBANOS = "escribanos"
    CARGOS = "cargos"
    BOLETAS = "boletas"
    PAGOS = "pagos"


class Severidad(StrEnum):
    # La fila no se carga (y tampoco las que dependen de ella).
    BLOQUEANTE = "BLOQUEANTE"
    # La fila se carga; queda para revisar.
    ADVERTENCIA = "ADVERTENCIA"


class ModoCorrida(StrEnum):
    # Todo dentro de una transacción que se revierte: deja el informe y las observaciones.
    SIMULACRO = "SIMULACRO"
    # Carga real: una sola vez por base, con simulacros cuadrados y conformidades previas.
    DEFINITIVA = "DEFINITIVA"


class EstadoCorrida(StrEnum):
    EN_CURSO = "EN_CURSO"
    SIMULADA = "SIMULADA"
    CARGADA = "CARGADA"
    FALLIDA = "FALLIDA"


class AreaConformidad(StrEnum):
    TESORERIA = "TESORERIA"
    CAJA = "CAJA"


NOMBRE_AREA = {AreaConformidad.TESORERIA: "Tesorería", AreaConformidad.CAJA: "Caja"}

# Rol que habilita a firmar por cada área.
ROL_DEL_AREA = {
    AreaConformidad.TESORERIA: "ROLE_TESORERIA",
    AreaConformidad.CAJA: "ROLE_CAJA",
}


class EstadoBoletaHistorica(StrEnum):
    IMPAGA = "IMPAGA"
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"
