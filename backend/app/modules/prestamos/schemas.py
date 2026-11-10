"""Contratos de préstamos. Importes y tasas como texto decimal (sin float)."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.modules.parametros.schemas import Money, Rate
from app.modules.prestamos.catalog import EstadoCuota, EstadoPrestamo, Moneda, Sistema

Codigo = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_]{2,49}$")]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
Plazo = Annotated[int, Field(gt=0, le=360)]
Porcentaje = Annotated[Rate, Field(gt=0, le=100)]


class LineaIn(BaseModel):
    codigo: Codigo
    nombre: Nombre
    descripcion: Texto | None = None
    sistema: Sistema
    plazo_minimo: Plazo
    plazo_maximo: Plazo
    monto_minimo: Money
    monto_maximo: Money
    tna: Rate
    afectacion_maxima: Annotated[Rate, Field(gt=0)]
    requiere_garante: bool = False
    moneda: Moneda = Moneda.ARS
    garantia: Texto | None = None
    requisito_conducta: Texto | None = None
    # Capital sobre el valor del inmueble hipotecado, en %.
    relacion_capital_hipoteca: Porcentaje | None = None
    requiere_certificado_ingresos: bool = False
    requiere_certificado_bienes: bool = False
    antiguedad_minima_meses: Annotated[int, Field(gt=0, le=600)] | None = None
    es_ejemplo: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def _rangos(self) -> "LineaIn":
        if self.plazo_maximo < self.plazo_minimo:
            raise ValueError("El plazo máximo no puede ser menor que el mínimo.")
        if self.monto_minimo <= 0 or self.monto_maximo < self.monto_minimo:
            raise ValueError("El monto máximo no puede ser menor que el mínimo.")
        return self


class LineaOut(LineaIn):
    id: uuid.UUID


class SimulacionIn(BaseModel):
    linea_id: uuid.UUID
    capital: Annotated[Money, Field(gt=0)]
    cuotas: Plazo
    ingreso_neto: Annotated[Money, Field(gt=0)] | None = None
    # Solo personal: evaluar para un escribano. El escribano simula siempre para sí mismo.
    escribano_id: uuid.UUID | None = None
    garante_escribano_id: uuid.UUID | None = None


class SolicitudIn(BaseModel):
    escribano_id: uuid.UUID
    linea_id: uuid.UUID
    capital: Annotated[Money, Field(gt=0)]
    cuotas: Plazo
    ingreso_neto: Annotated[Money, Field(gt=0)]
    garante_escribano_id: uuid.UUID | None = None
    observaciones: Texto | None = None


class RechazoIn(BaseModel):
    motivo: Motivo


class PagoIn(BaseModel):
    fecha_pago: date
    importe: Annotated[Money, Field(gt=0)]


class CuotaOut(BaseModel):
    numero: int
    vencimiento: date
    saldo_inicial: Money
    amortizacion: Money
    interes: Money
    cuota: Money
    saldo_final: Money
    estado: EstadoCuota
    vencida: bool
    fecha_pago: date | None
    importe_pagado: Money | None


class Totales(BaseModel):
    capital: Money
    intereses: Money
    total: Money


class EvaluacionOut(BaseModel):
    moneda: Moneda
    sistema: Sistema
    tna: Rate
    tasa_es_ejemplo: bool
    capital: Money
    cuotas: int
    cuota_maxima: Money
    otras_cuotas: Money
    afectacion: Rate | None
    afectacion_maxima: Rate
    requiere_garante: bool
    # Motivos por los que no se puede otorgar (vacío = viable).
    impedimentos: list[str]
    # Avisos que no impiden otorgar pero hay que revisar (p. ej. antigüedad no verificable).
    avisos: list[str]
    plan: list[CuotaOut]
    totales: Totales


class PersonaResumen(BaseModel):
    id: uuid.UUID
    apellido_nombre: str
    matricula_numero: int | None


class PrestamoOut(BaseModel):
    id: uuid.UUID
    numero: int
    escribano: PersonaResumen
    garante: PersonaResumen | None
    linea_id: uuid.UUID
    linea_nombre: str
    estado: EstadoPrestamo
    moneda: Moneda
    sistema: Sistema
    tna: Rate
    tasa_es_ejemplo: bool
    capital: Money
    cuotas: int
    # Datos de la evaluación del titular: no se envían a quien es solo garante.
    ingreso_neto: Money | None
    otras_cuotas: Money | None
    cuota_maxima: Money
    afectacion: Rate | None
    afectacion_maxima: Rate
    observaciones: str | None
    motivo_rechazo: str | None
    fecha_otorgamiento: date | None
    creado_por: str | None
    resuelto_por: str | None
    resuelto_en: datetime | None
    created_at: datetime
    saldo_capital: Money | None
    cuotas_pagadas: int
    cuotas_vencidas: int


class CobroCuotaMPOut(BaseModel):
    """Pago de una cuota con Mercado Pago, tal como lo informó Mercado Pago."""

    id: uuid.UUID
    cuota: int
    # Estado según Mercado Pago (catalog.EstadoPagoMP de pagos).
    estado: str
    medio_pago: str | None
    importe_pagado: Money | None
    aprobado_en: datetime | None
    # Tesorería lo confirmó: la cuota quedó pagada con este cobro.
    confirmado_en: datetime | None
    # Aprobado por Mercado Pago y todavía sin confirmar por Tesorería.
    a_confirmar: bool


class PrestamoDetalle(PrestamoOut):
    plan: list[CuotaOut]
    totales: Totales
    # Solo en solicitudes: cómo quedaría hoy la evaluación (puede cambiar hasta otorgar).
    impedimentos_actuales: list[str]
    avisos_actuales: list[str]
    puede_resolver: bool
    # Pagos con Mercado Pago informados (sin los cobros que nadie pagó), los últimos primero.
    cobros_mp: list[CobroCuotaMPOut] = []
    # Quien mira tomó el préstamo y puede pagar la próxima cuota con Mercado Pago.
    puede_pagar_mp: bool = False
