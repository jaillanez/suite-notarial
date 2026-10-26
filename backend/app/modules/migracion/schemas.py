import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints

from app.modules.migracion.catalog import AreaConformidad, EstadoCorrida, ModoCorrida, Severidad


class ConformidadOut(BaseModel):
    area: AreaConformidad
    firmante: str
    firmada_en: datetime
    observaciones: str | None


class CorridaOut(BaseModel):
    id: uuid.UUID
    modo: ModoCorrida
    estado: EstadoCorrida
    huella_lote: str
    homologacion: str
    homologacion_ejemplo: bool
    operador: str
    created_at: datetime
    finalizada_en: datetime | None
    duracion_ms: int | None
    cuadra: bool | None
    bloqueantes: int | None
    advertencias: int | None
    conformidades: list[ConformidadOut]


class CorridaDetalle(CorridaOut):
    # Cuadratura: totales y conteos por entidad, saldos y observaciones por código.
    informe: dict[str, Any] | None
    error: str | None
    # Tabla de homologación que cubren las conformidades (códigos del origen → Suite).
    huella_homologacion: str
    homologacion_tablas: dict[str, dict[str, str]]
    # Lo que falta para hacer la carga definitiva de este mismo lote (vacío: habilitada).
    pendiente_para_definitiva: list[str]


class ObservacionOut(BaseModel):
    entidad: str
    fila: int
    codigo_legado: str
    codigo: str
    severidad: Severidad
    mensaje: str


class ObservacionesPage(BaseModel):
    items: list[ObservacionOut]
    total: int
    page: int
    page_size: int


class ConformidadIn(BaseModel):
    area: AreaConformidad
    observaciones: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
    ) = None
