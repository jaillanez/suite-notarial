"""Contratos de la API de aportes y puntos (Ley 7231). Importes y puntos como texto decimal."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

from app.modules.previsional.catalog import EstadoVinculo, Vinculacion

# Sin validación de signo: es el dato histórico tal como lo registró la Caja.
Importe = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]
Puntos = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.6f}", return_type=str)]


class EscribanoResumen(BaseModel):
    id: uuid.UUID
    apellido_nombre: str
    matricula_numero: int | None
    tipo_documento: str
    numero_documento: str | None


class FilaPuntosOut(BaseModel):
    anio: int
    fecha_inicio: date
    fecha_cierre: date
    aportes: Importe
    puntos: Puntos


class OrigenOut(BaseModel):
    nombre_origen: str
    vinculacion: Vinculacion
    ejercicios: int


class InformePuntosOut(BaseModel):
    escribano: EscribanoResumen
    filas: list[FilaPuntosOut]
    # Nombres de la planilla que alimentan este informe y cómo se vincularon.
    origenes: list[OrigenOut]
    total_aportes: Importe
    total_puntos: Puntos


class SinVincularOut(BaseModel):
    nombre_origen: str
    estado: EstadoVinculo
    ejercicios: int
    primer_anio: int
    ultimo_anio: int
    total_aportes: Importe
    total_puntos: Puntos
    # APROXIMADA: el escribano sugerido (sin vínculo). HEREDADA: aquel al que ya cuentan.
    escribano: EscribanoResumen | None


class VincularIn(BaseModel):
    nombre_origen: str = Field(min_length=1, max_length=200)
    escribano_id: uuid.UUID
    motivo: str | None = Field(default=None, max_length=1000)


class RechazarSugerenciaIn(BaseModel):
    nombre_origen: str = Field(min_length=1, max_length=200)
    motivo: str = Field(min_length=5, max_length=1000)


class VincularOut(BaseModel):
    filas: int


class EstadoCalculoOut(BaseModel):
    habilitado: bool
    motivo: str
