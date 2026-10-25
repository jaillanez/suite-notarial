"""Contratos de DDJJ y boletas. Montos como texto decimal (sin float)."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from app.modules.ddjj.catalog import CategoriaActo, EstadoBoleta, EstadoDDJJ, TipoProtocolo
from app.modules.padron.catalog import Cargo
from app.modules.parametros.schemas import Money

PERIODO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _periodo(value: str) -> str:
    if not PERIODO_RE.match(value):
        raise ValueError("El período tiene el formato AAAA-MM.")
    return value


Periodo = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_periodo)]
# Base imponible: hasta 16 enteros (Numeric(18,2)).
BaseImponible = Annotated[Money, Field(max_digits=18)]
Naturaleza = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class RegistroResumen(BaseModel):
    id: uuid.UUID
    numero_registro: int
    nombre_fantasia: str | None
    departamento: str


class EscribanoResumen(BaseModel):
    id: uuid.UUID
    apellido_nombre: str
    matricula_numero: int
    cargo: Cargo


class RegistroOperable(RegistroResumen):
    escribanos: list[EscribanoResumen]


class DeclaracionIn(BaseModel):
    registro_id: uuid.UUID
    periodo: Periodo


class ActoIn(BaseModel):
    escribano_id: uuid.UUID
    tipo_protocolo: TipoProtocolo = TipoProtocolo.GENERAL
    numero_escritura: int = Field(gt=0, le=1_000_000)
    folio: int | None = Field(default=None, gt=0, le=1_000_000)
    fecha_acto: date
    naturaleza: Naturaleza
    categoria: CategoriaActo
    base_imponible: BaseImponible = Decimal("0.00")

    @model_validator(mode="after")
    def _base_segun_categoria(self) -> "ActoIn":
        con_valor = self.categoria is CategoriaActo.ESCRITURA_CON_VALOR
        if con_valor and self.base_imponible <= 0:
            raise ValueError("Una escritura con valor necesita la base imponible.")
        if not con_valor and self.base_imponible != 0:
            raise ValueError("Solo las escrituras con valor llevan base imponible.")
        return self


class BajaActo(BaseModel):
    motivo: Motivo


class ActoOut(BaseModel):
    id: uuid.UUID
    escribano_id: uuid.UUID
    escribano: str
    matricula_numero: int
    cargo: Cargo
    tipo_protocolo: TipoProtocolo
    numero_escritura: int
    folio: int | None
    fecha_acto: date
    naturaleza: str
    categoria: CategoriaActo
    base_imponible: Money
    # En borrador es el aporte estimado con los parámetros vigentes; presentada, el congelado.
    aporte: Money | None
    vigencia_id: uuid.UUID | None


class AporteActoOut(BaseModel):
    acto_id: uuid.UUID
    aporte: Money


class LiquidacionOut(BaseModel):
    aportes: list[AporteActoOut]
    vencimiento: date
    fecha_pago: date
    total_protocolos: Money
    aporte_minimo: Money
    excedente: Money
    aporte_medico: Money
    cantidad_aportes_medicos: int
    total_en_termino: Money
    dias_mora: int
    interes_mora: Money
    total_a_pagar: Money
    # Algún parámetro usado está marcado como ejemplo (no oficial).
    usa_valores_de_ejemplo: bool


class BoletaOut(BaseModel):
    id: uuid.UUID
    numero: int
    codigo_verificacion: str
    ddjj_id: uuid.UUID
    registro: RegistroResumen
    periodo: str
    numero_rectificativa: int
    estado: EstadoBoleta
    fecha_emision: date
    fecha_vencimiento: date
    fecha_pago: date
    dias_mora: int
    total_protocolos: Money
    aporte_minimo: Money
    excedente: Money
    aporte_medico: Money
    cantidad_aportes_medicos: int
    total_en_termino: Money
    interes_mora: Money
    total_a_pagar: Money
    created_at: datetime
    emitida_por: str | None
    anulada_en: datetime | None
    motivo_anulacion: str | None


class DeclaracionOut(BaseModel):
    id: uuid.UUID
    registro: RegistroResumen
    periodo: str
    numero_rectificativa: int
    estado: EstadoDDJJ
    observaciones: str | None
    fecha_presentacion: datetime | None
    presentada_por: str | None
    rectifica_a_id: uuid.UUID | None
    cantidad_actos: int
    total_protocolos: Money | None
    vencimiento: date | None
    created_at: datetime


class DeclaracionDetalle(DeclaracionOut):
    actos: list[ActoOut]
    boletas: list[BoletaOut]
    escribanos: list[EscribanoResumen]
    puede_operar: bool


class PresentarIn(BaseModel):
    fecha_pago: date
    observaciones: Texto | None = None


class EmitirBoletaIn(BaseModel):
    fecha_pago: date


class VencimientoIn(BaseModel):
    fecha_vencimiento: date


class VencimientoOut(BaseModel):
    periodo: str
    fecha_vencimiento: date


class VerificacionOut(BaseModel):
    """Lo mínimo para validar una boleta impresa sin exponer datos personales."""

    numero: int
    codigo_verificacion: str
    registro_numero: int
    periodo: str
    estado: EstadoBoleta
    fecha_emision: date
    fecha_pago: date
    total_a_pagar: Money
    integra: bool
