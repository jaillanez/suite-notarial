"""Contratos de DDJJ y boletas. Montos como texto decimal (sin float)."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from app.modules.ddjj.catalog import (
    CategoriaActo,
    EstadoBoleta,
    EstadoDDJJ,
    MotivoExencion,
    TipoProtocolo,
)
from app.modules.ddjj.protocolo import NivelControl
from app.modules.padron.catalog import Cargo
from app.modules.pagos.catalog import EstadoComprobante, OrigenComprobante
from app.modules.parametros.catalog import PeriodoTasa
from app.modules.parametros.schemas import Money, Rate

PERIODO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _periodo(value: str) -> str:
    if not PERIODO_RE.match(value):
        raise ValueError("El período tiene el formato AAAA-MM.")
    if not 2000 <= int(value[:4]) <= 2100:
        raise ValueError("El año del período está fuera de rango.")
    return value


Periodo = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_periodo)]
# Base imponible: hasta 16 enteros (Numeric(18,2)).
BaseImponible = Annotated[Money, Field(max_digits=18)]
Naturaleza = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
DetalleExencion = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
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
    # Otro acto de una escritura ya cargada en esta DDJJ (aporte múltiple).
    acto_multiple: bool = False
    # Obligatorio para un acto exento; con «otro motivo», también el detalle.
    motivo_exencion: MotivoExencion | None = None
    detalle_exencion: DetalleExencion | None = None

    @model_validator(mode="after")
    def _base_segun_categoria(self) -> "ActoIn":
        con_valor = self.categoria is CategoriaActo.ESCRITURA_CON_VALOR
        if con_valor and self.base_imponible <= 0:
            raise ValueError("Una escritura con valor necesita la base imponible.")
        if not con_valor and self.base_imponible != 0:
            raise ValueError("Solo las escrituras con valor llevan base imponible.")
        return self

    @model_validator(mode="after")
    def _motivo_de_exencion(self) -> "ActoIn":
        self.detalle_exencion = self.detalle_exencion or None  # "" (o solo espacios) = sin detalle
        if self.categoria is not CategoriaActo.EXENTO:
            if self.motivo_exencion is not None or self.detalle_exencion is not None:
                raise ValueError("Solo un acto exento lleva motivo de exención.")
            return self
        if self.motivo_exencion is None:
            raise ValueError("Indicá el motivo de la exención.")
        if self.motivo_exencion is MotivoExencion.OTRO and len(self.detalle_exencion or "") < 3:
            raise ValueError("Detallá el motivo de la exención.")
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
    orden_en_escritura: int
    folio: int | None
    fecha_acto: date
    naturaleza: str
    categoria: CategoriaActo
    base_imponible: Money
    motivo_exencion: MotivoExencion | None
    detalle_exencion: str | None
    # En borrador es el aporte estimado con los parámetros vigentes; presentada, el congelado.
    aporte: Money | None
    vigencia_id: uuid.UUID | None


class AporteActoOut(BaseModel):
    acto_id: uuid.UUID
    aporte: Money


class TramoMoraOut(BaseModel):
    """Días de atraso en que rigió una misma tasa (`desde` y `hasta` inclusive)."""

    desde: date
    hasta: date
    dias: int
    tasa: Rate
    periodo_tasa: PeriodoTasa
    interes: Money


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
    tramos_mora: list[TramoMoraOut]
    total_a_pagar: Money
    # Algún parámetro usado está marcado como ejemplo (no oficial).
    usa_valores_de_ejemplo: bool


class ComprobanteResumen(BaseModel):
    """Último comprobante adjuntado a la boleta (el detalle está en /api/v1/pagos)."""

    id: uuid.UUID
    origen: OrigenComprobante
    estado: EstadoComprobante
    importe_declarado: Money
    motivo_rechazo: str | None
    created_at: datetime


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
    tramos_mora: list[TramoMoraOut]
    total_a_pagar: Money
    created_at: datetime
    emitida_por: str | None
    anulada_en: datetime | None
    motivo_anulacion: str | None
    comprobante: ComprobanteResumen | None = None


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


class ControlOut(BaseModel):
    codigo: str
    nivel: NivelControl
    mensaje: str


class TramoOut(BaseModel):
    desde: int
    hasta: int


class HuecoOut(BaseModel):
    tipo_protocolo: TipoProtocolo
    tramos: list[TramoOut]
    total: int


class DeclaracionDetalle(DeclaracionOut):
    actos: list[ActoOut]
    boletas: list[BoletaOut]
    escribanos: list[EscribanoResumen]
    puede_operar: bool
    # Controles del libro de protocolo: por acto (solo los que tienen algo) y números salteados.
    controles: dict[uuid.UUID, list[ControlOut]]
    huecos: list[HuecoOut]
    # Número de escritura que sigue en cada protocolo (carga rápida del próximo acto).
    proximos_numeros: dict[TipoProtocolo, int]


class VerificacionActoIn(BaseModel):
    """Acto a medio cargar: lo que haya, para ver el aporte y los controles mientras se tipea."""

    tipo_protocolo: TipoProtocolo = TipoProtocolo.GENERAL
    numero_escritura: int | None = Field(default=None, gt=0, le=1_000_000)
    folio: int | None = Field(default=None, gt=0, le=1_000_000)
    fecha_acto: date | None = None
    categoria: CategoriaActo | None = None
    base_imponible: BaseImponible | None = None
    acto_multiple: bool = False
    # Al editar o revisar un acto ya cargado.
    excluir_acto_id: uuid.UUID | None = None


class VerificacionActoOut(BaseModel):
    # Aporte estimado con los parámetros vigentes del período (None si faltan datos).
    aporte: Money | None
    controles: list[ControlOut]


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
