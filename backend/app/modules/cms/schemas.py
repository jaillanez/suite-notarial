"""Contratos del sitio institucional y su administración."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.modules.cms.catalog import EstadoPublicacion, TipoDocumento

Slug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=150
    ),
]
Titulo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Corto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)]
Resumen = Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)]
Contenido = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=50_000)
]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


# --------------------------------------------------------------------------- autoridades


class AutoridadIn(BaseModel):
    cargo: Corto
    nombre: Corto
    orden: int = Field(default=0, ge=0, le=999)
    mandato_desde: date | None = None
    mandato_hasta: date | None = None

    @model_validator(mode="after")
    def _mandato(self) -> "AutoridadIn":
        if self.mandato_desde and self.mandato_hasta and self.mandato_hasta < self.mandato_desde:
            raise ValueError("El fin del mandato no puede ser anterior al inicio.")
        return self


class AutoridadUpdate(AutoridadIn):
    is_active: bool = True


class AutoridadOut(BaseModel):
    id: uuid.UUID
    cargo: str
    nombre: str
    orden: int
    mandato_desde: date | None
    mandato_hasta: date | None
    is_active: bool


# --------------------------------------------------------------------------- novedades


class NovedadIn(BaseModel):
    titulo: Titulo
    resumen: Resumen | None = None
    contenido: Contenido
    # Si falta, se arma a partir del título.
    slug: Slug | None = None


class EstadoIn(BaseModel):
    estado: EstadoPublicacion


class NovedadOut(BaseModel):
    id: uuid.UUID
    slug: str
    titulo: str
    resumen: str | None
    contenido: str
    estado: EstadoPublicacion
    fecha_publicacion: datetime | None
    autor: str | None
    created_at: datetime
    updated_at: datetime


class NovedadResumen(BaseModel):
    slug: str
    titulo: str
    resumen: str | None
    fecha_publicacion: datetime


class NovedadPublica(NovedadResumen):
    contenido: str


# --------------------------------------------------------------------------- documentos


class DocumentoIn(BaseModel):
    tipo: TipoDocumento
    ejercicio: int = Field(ge=1950, le=2200)
    titulo: Titulo
    descripcion: Texto | None = None
    slug: Slug | None = None


class DocumentoUpdate(BaseModel):
    titulo: Titulo
    descripcion: Texto | None = None


class VersionOut(BaseModel):
    version: int
    nombre_original: str
    sha256: str
    tamano_bytes: int
    paginas: int
    motivo: str | None
    subido_por: str | None
    created_at: datetime
    url: str
    # Resultado de verificar la huella (solo en la vista de administración).
    integra: bool | None = None


class DocumentoOut(BaseModel):
    id: uuid.UUID
    slug: str
    tipo: TipoDocumento
    ejercicio: int
    titulo: str
    descripcion: str | None
    estado: EstadoPublicacion
    fecha_publicacion: datetime | None
    url: str
    versiones: list[VersionOut]


class DocumentoPublico(BaseModel):
    slug: str
    tipo: TipoDocumento
    tipo_texto: str
    ejercicio: int
    titulo: str
    descripcion: str | None
    fecha_publicacion: datetime
    url: str
    paginas: int
    tamano_bytes: int
    sha256: str
    version: int
    actualizado: datetime
    versiones_anteriores: list[VersionOut]


class SitioPublico(BaseModel):
    autoridades: list[AutoridadOut]
    novedades: list[NovedadResumen]
    documentos: list[DocumentoPublico]
