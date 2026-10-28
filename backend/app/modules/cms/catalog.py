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


class SeccionNovedad(StrEnum):
    """Secciones de las notas, como en el sitio original de la Caja."""

    NOVEDADES = "NOVEDADES"
    COMUNICADOS = "COMUNICADOS"
    APORTES = "APORTES"
    INSTITUCIONAL = "INSTITUCIONAL"


SECCION_NOVEDAD_TEXTO: dict[SeccionNovedad, str] = {
    SeccionNovedad.NOVEDADES: "Novedades",
    SeccionNovedad.COMUNICADOS: "Comunicados de la Caja",
    SeccionNovedad.APORTES: "Aportes",
    SeccionNovedad.INSTITUCIONAL: "Institucional",
}


class GrupoPagina(StrEnum):
    """Menú del sitio en el que aparece una página institucional."""

    CAJA = "CAJA"
    NORMATIVA = "NORMATIVA"


GRUPO_PAGINA_TEXTO: dict[GrupoPagina, str] = {
    GrupoPagina.CAJA: "Caja",
    GrupoPagina.NORMATIVA: "Normativa",
}


class Distribucion(StrEnum):
    """Cómo se reparte una fila de la portada en 4 columnas (ancho de cada nota)."""

    UNA = "4"
    TRES_UNA = "3+1"
    DOS_DOS = "2+2"
    DOS_UNA_UNA = "2+1+1"
    CUATRO = "1+1+1+1"


ANCHOS: dict[Distribucion, tuple[int, ...]] = {
    d: tuple(int(x) for x in d.value.split("+")) for d in Distribucion
}

# Imágenes de las notas: tipo real por magic bytes (nunca por la extensión).
MIME_IMAGEN: dict[str, str] = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGEN_MB = 5
MAX_DESTACADAS = 5
MAX_FILAS = 8
