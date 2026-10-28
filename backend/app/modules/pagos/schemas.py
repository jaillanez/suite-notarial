"""Contratos de comprobantes y conciliación. Importes como texto decimal (sin float)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer, StringConstraints

from app.modules.ddjj.schemas import RegistroResumen
from app.modules.pagos.catalog import (
    EstadoComprobante,
    EstadoPagoMP,
    OrigenComprobante,
    ResultadoConciliacion,
)
from app.modules.parametros.schemas import Money

Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
# Importe con signo (diferencias), como texto decimal.
ImporteConSigno = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]
Corto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ComprobanteIn(BaseModel):
    """Datos de la transferencia; el archivo viaja aparte en el formulario multipart."""

    fecha_transferencia: date
    numero_operacion: Corto
    importe_declarado: Money
    banco_origen: Corto | None = None


class AprobacionIn(BaseModel):
    importe_confirmado: Money
    fecha_acreditacion: date
    identificador_extracto: Corto | None = None
    observaciones: Texto | None = None


class RechazoIn(BaseModel):
    motivo: Motivo


class ConciliacionOut(BaseModel):
    resultado: ResultadoConciliacion
    importe_confirmado: Money | None
    fecha_acreditacion: date | None
    identificador_extracto: str | None
    observaciones: str | None
    operador: str | None
    created_at: datetime


class BoletaResumen(BaseModel):
    id: uuid.UUID
    numero: int
    ddjj_id: uuid.UUID
    registro: RegistroResumen
    periodo: str
    estado: str
    fecha_pago: date
    total_a_pagar: Money


class PagoMercadoPagoOut(BaseModel):
    """Lo que informó Mercado Pago del pago (consultado a su API, no al navegador)."""

    id: uuid.UUID
    boleta_id: uuid.UUID
    estado: EstadoPagoMP
    estado_detalle: str | None
    mp_payment_id: str | None
    medio_pago: str | None
    importe_boleta: Money
    importe_pagado: Money | None
    comision: Money | None
    importe_neto: Money | None
    aprobado_en: datetime | None
    comprobante_id: uuid.UUID | None
    created_at: datetime


class ComprobanteOut(BaseModel):
    id: uuid.UUID
    boleta: BoletaResumen
    origen: OrigenComprobante
    # Vacíos en un comprobante de Mercado Pago (no tiene archivo).
    nombre_original: str | None
    mime_type: str | None
    tamano_bytes: int | None
    fecha_transferencia: date
    banco_origen: str | None
    numero_operacion: str
    importe_declarado: Money
    # Lo declarado menos el total de la boleta (cero cuando coincide).
    diferencia: ImporteConSigno
    estado: EstadoComprobante
    motivo_rechazo: str | None
    subido_por: str | None
    created_at: datetime
    revisado_en: datetime | None
    conciliacion: ConciliacionOut | None
    # Solo en un comprobante de Mercado Pago.
    mercado_pago: PagoMercadoPagoOut | None = None


class MercadoPagoEstadoOut(BaseModel):
    habilitado: bool


class InicioPagoMPOut(BaseModel):
    """Dirección de Mercado Pago a la que se lleva al escribano para pagar."""

    url_pago: str
