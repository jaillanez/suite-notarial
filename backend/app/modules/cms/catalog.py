"""Valores de dominio del sitio institucional (Módulo 8)."""

from enum import StrEnum


class EstadoPublicacion(StrEnum):
    """Novedades y documentos: solo lo PUBLICADO se ve en el sitio público."""

    BORRADOR = "BORRADOR"
    PUBLICADO = "PUBLICADO"
    ARCHIVADO = "ARCHIVADO"


class TipoDocumento(StrEnum):
    ESTADO_CONTABLE = "ESTADO_CONTABLE"
    MEMORIA_ANUAL = "MEMORIA_ANUAL"
    RESOLUCION = "RESOLUCION"
    OTRO = "OTRO"


TIPO_DOCUMENTO_TEXTO: dict[TipoDocumento, str] = {
    TipoDocumento.ESTADO_CONTABLE: "Estados contables",
    TipoDocumento.MEMORIA_ANUAL: "Memoria anual",
    TipoDocumento.RESOLUCION: "Resoluciones",
    TipoDocumento.OTRO: "Otros documentos",
}

# Transiciones editoriales. Un archivado puede volver a publicarse; nada vuelve a borrador.
TRANSICIONES: dict[EstadoPublicacion, frozenset[EstadoPublicacion]] = {
    EstadoPublicacion.BORRADOR: frozenset({EstadoPublicacion.PUBLICADO}),
    EstadoPublicacion.PUBLICADO: frozenset({EstadoPublicacion.ARCHIVADO}),
    EstadoPublicacion.ARCHIVADO: frozenset({EstadoPublicacion.PUBLICADO}),
}
