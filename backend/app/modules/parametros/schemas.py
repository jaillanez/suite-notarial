"""Contratos del motor paramétrico. Montos y tasas viajan como texto decimal (sin float)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints, model_validator

from app.modules.parametros.catalog import EstadoVigencia, ReglaRedondeo, TipoConcepto

# Se serializan como string para que ningún cliente los convierta a punto flotante.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=15, decimal_places=2),
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str),
]
Rate = Annotated[
    Decimal,
    Field(ge=0, le=100, max_digits=18, decimal_places=4),
    PlainSerializer(lambda v: f"{v:.4f}", return_type=str),
]
Codigo = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_]{2,49}$")]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
Resolucion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)]


class ConceptoIn(BaseModel):
    codigo: Codigo
    nombre: Nombre
    tipo: TipoConcepto
    descripcion: Texto | None = None


class ConceptoUpdate(BaseModel):
    nombre: Nombre | None = None
    descripcion: Texto | None = None
    is_active: bool | None = None


class VigenciaIn(BaseModel):
    fecha_desde: date
    fecha_hasta: date | None = None
    porcentaje: Rate | None = None
    monto_fijo: Money | None = None
    monto_minimo: Money | None = None
    monto_maximo: Money | None = None
    tasa_mensual: Rate | None = None
    dias_gracia: int | None = Field(default=None, ge=0, le=90)
    regla_redondeo: ReglaRedondeo = ReglaRedondeo.HALF_UP
    resolucion_respaldo: Resolucion
    motivo: Motivo

    @model_validator(mode="after")
    def _coherencia(self) -> "VigenciaIn":
        if self.fecha_hasta is not None and self.fecha_hasta < self.fecha_desde:
            raise ValueError("La fecha hasta no puede ser anterior a la fecha desde.")
        if (
            self.monto_minimo is not None
            and self.monto_maximo is not None
            and self.monto_minimo > self.monto_maximo
        ):
            raise ValueError("El mínimo no puede superar al tope.")
        return self


class Rechazo(BaseModel):
    motivo: Motivo


class VigenciaOut(BaseModel):
    id: uuid.UUID
    concepto_id: uuid.UUID
    concepto_codigo: str
    version: int
    fecha_desde: date
    fecha_hasta: date | None
    porcentaje: Rate | None
    monto_fijo: Money | None
    monto_minimo: Money | None
    monto_maximo: Money | None
    tasa_mensual: Rate | None
    dias_gracia: int | None
    regla_redondeo: ReglaRedondeo
    es_ejemplo: bool
    estado: EstadoVigencia
    resolucion_respaldo: str
    motivo: str
    created_at: datetime
    creado_por: str | None
    aprobado_por: str | None
    fecha_aprobacion: datetime | None
    motivo_rechazo: str | None


class ConceptoOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    tipo: TipoConcepto
    descripcion: str | None
    is_active: bool
    vigente: VigenciaOut | None
    pendientes: int


class SimulacionIn(BaseModel):
    concepto_codigo: Codigo
    fecha: date
    base_imponible: Money | None = None
    monto: Money | None = None
    vencimiento: date | None = None
    fecha_pago: date | None = None


class SimulacionOut(BaseModel):
    vigencia: VigenciaOut
    resultado: Money
    dias_mora: int | None = None
    detalle: str
