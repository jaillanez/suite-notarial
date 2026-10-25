"""Contratos del padrón notarial."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

from app.common.cuit import InvalidCuitError, normalize_cuit
from app.modules.padron.catalog import (
    DEPARTAMENTOS_SAN_JUAN,
    Cargo,
    EstadoMatricula,
    EstadoRegistro,
    TipoDocumento,
)

Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
Corto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
Documento = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9A-Za-z]{6,15}$")]
Telefono = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]


def _cuit(value: str) -> str:
    try:
        return normalize_cuit(value)
    except InvalidCuitError as exc:
        raise ValueError(str(exc)) from exc


def _departamento(value: str) -> str:
    if value not in DEPARTAMENTOS_SAN_JUAN:
        raise ValueError("Departamento inexistente en la Provincia de San Juan.")
    return value


# --------------------------------------------------------------------------- circunscripciones


class CircunscripcionIn(BaseModel):
    nombre: Nombre
    descripcion: Texto | None = None


class CircunscripcionUpdate(BaseModel):
    nombre: Nombre | None = None
    descripcion: Texto | None = None
    is_active: bool | None = None


class CircunscripcionOut(BaseModel):
    id: uuid.UUID
    nombre: str
    descripcion: str | None
    is_active: bool


# --------------------------------------------------------------------------- personas


class PersonaIn(BaseModel):
    cuit: str
    tipo_documento: TipoDocumento = TipoDocumento.DNI
    numero_documento: Documento
    apellido: Nombre
    nombre: Nombre
    fecha_nacimiento: date | None = None
    email: EmailStr | None = None
    telefono: Telefono | None = None
    domicilio_real: Texto | None = None

    @field_validator("cuit")
    @classmethod
    def _v_cuit(cls, value: str) -> str:
        return _cuit(value)


class PersonaUpdate(BaseModel):
    tipo_documento: TipoDocumento | None = None
    numero_documento: Documento | None = None
    apellido: Nombre | None = None
    nombre: Nombre | None = None
    fecha_nacimiento: date | None = None
    email: EmailStr | None = None
    telefono: Telefono | None = None
    domicilio_real: Texto | None = None


class PersonaOut(BaseModel):
    id: uuid.UUID
    cuit: str
    tipo_documento: str
    numero_documento: str
    apellido: str
    nombre: str
    fecha_nacimiento: date | None
    email: str | None
    telefono: str | None
    domicilio_real: str | None


# --------------------------------------------------------------------------- registros


class RegistroIn(BaseModel):
    numero_registro: int = Field(gt=0, lt=100_000)
    nombre_fantasia: Corto | None = None
    circunscripcion_id: uuid.UUID
    departamento: str
    domicilio_legal: Texto
    telefono: Telefono | None = None
    email: EmailStr | None = None
    fecha_creacion: date | None = None

    @field_validator("departamento")
    @classmethod
    def _v_dep(cls, value: str) -> str:
        return _departamento(value)


class RegistroUpdate(BaseModel):
    nombre_fantasia: Corto | None = None
    circunscripcion_id: uuid.UUID | None = None
    departamento: str | None = None
    domicilio_legal: Texto | None = None
    telefono: Telefono | None = None
    email: EmailStr | None = None
    fecha_creacion: date | None = None

    @field_validator("departamento")
    @classmethod
    def _v_dep(cls, value: str | None) -> str | None:
        return None if value is None else _departamento(value)


class RegistroCierre(BaseModel):
    motivo: Motivo


class CargoResumen(BaseModel):
    adscripcion_id: uuid.UUID
    escribano_id: uuid.UUID
    matricula_numero: int
    apellido_nombre: str
    cargo: Cargo
    fecha_desde: date
    estado_matricula: EstadoMatricula


class RegistroOut(BaseModel):
    id: uuid.UUID
    numero_registro: int
    nombre_fantasia: str | None
    circunscripcion: CircunscripcionOut
    departamento: str
    domicilio_legal: str
    telefono: str | None
    email: str | None
    fecha_creacion: date | None
    estado: EstadoRegistro
    titular: CargoResumen | None = None
    cantidad_adscriptos: int = 0


class RegistroDetalle(RegistroOut):
    cargos_vigentes: list[CargoResumen]


# --------------------------------------------------------------------------- escribanos


class EscribanoIn(BaseModel):
    persona: PersonaIn
    matricula_numero: int = Field(gt=0, lt=1_000_000)
    tomo: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    folio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    fecha_matriculacion: date


class EscribanoUpdate(BaseModel):
    tomo: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    folio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    fecha_matriculacion: date | None = None
    persona: PersonaUpdate | None = None


class EstadoCambio(BaseModel):
    nuevo_estado: EstadoMatricula
    motivo: Motivo
    resolucion_respaldo: Corto | None = None
    fecha_efectiva: date


class CargoAsignacion(BaseModel):
    registro_id: uuid.UUID
    cargo: Cargo
    fecha_desde: date
    resolucion_designacion: Corto | None = None


class CargoCierre(BaseModel):
    fecha_hasta: date
    motivo: Motivo


class CargoOut(BaseModel):
    id: uuid.UUID
    registro_id: uuid.UUID
    numero_registro: int
    cargo: Cargo
    resolucion_designacion: str | None
    fecha_desde: date
    fecha_hasta: date | None
    motivo_cierre: str | None
    is_current: bool


class HistorialOut(BaseModel):
    id: uuid.UUID
    estado_anterior: EstadoMatricula
    estado_nuevo: EstadoMatricula
    motivo: str
    resolucion_respaldo: str | None
    fecha_efectiva: date
    fecha_cambio: datetime
    operador_email: str | None


class EscribanoOut(BaseModel):
    id: uuid.UUID
    matricula_numero: int
    tomo: str | None
    folio: str | None
    fecha_matriculacion: date
    estado_matricula: EstadoMatricula
    apellido_nombre: str
    cuit: str
    numero_documento: str
    registro_actual: int | None
    cargo_actual: Cargo | None
    tiene_cuenta: bool


class EscribanoDetalle(EscribanoOut):
    persona: PersonaOut
    motivo_ultimo_cambio_estado: str | None
    fecha_ultimo_cambio_estado: datetime | None
    cargos: list[CargoOut]
    historial: list[HistorialOut]
