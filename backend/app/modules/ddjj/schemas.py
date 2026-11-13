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
    ModalidadBoleta,
    MotivoExencion,
    TipoProtocolo,
)
from app.modules.ddjj.protocolo import NivelControl
from app.modules.padron.catalog import Cargo
from app.modules.pagos.catalog import EstadoComprobante, OrigenComprobante
from app.modules.parametros.catalog import CriterioPluralidad, EstadoVigencia, PeriodoTasa
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
CodigoVademecum = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_]{2,59}$")
]
NombreVademecum = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
]
Sinonimos = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Resolucion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)]


def base_de(precio: Decimal | None, avaluo: Decimal | None) -> Decimal | None:
    """Base imponible del vademécum: «el mayor valor de precio o avalúo»."""
    if precio is None and avaluo is None:
        return None
    return max(precio or Decimal("0.00"), avaluo or Decimal("0.00"))


class RegistroResumen(BaseModel):
    id: uuid.UUID
    numero_registro: int
    nombre_fantasia: str | None
    departamento: str | None  # None: «a completar»


class EscribanoResumen(BaseModel):
    id: uuid.UUID
    apellido_nombre: str
    matricula_numero: int | None
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
    # Acto del vademécum vigente elegido: fija la categoría (y la exención). Sin vademécum, el
    # acto queda marcado para que la Caja lo revise (salvo una escritura sin efecto).
    vademecum_id: uuid.UUID | None = None
    # Con precio o avalúo, la base imponible es el mayor de los dos (la calcula el servidor).
    precio: BaseImponible | None = None
    avaluo: BaseImponible | None = None
    # Otro acto de una escritura ya cargada en esta DDJJ (aporte múltiple).
    acto_multiple: bool = False
    # Escritura con varios actos: ¿intervienen solo las mismas partes? Se aplica a todos los
    # actos de la escritura. Obligatorio en un acto múltiple: no hay respuesta por defecto.
    mismas_partes: bool | None = None
    # Obligatorio para un acto exento; con «otro motivo», también el detalle.
    motivo_exencion: MotivoExencion | None = None
    detalle_exencion: DetalleExencion | None = None

    @model_validator(mode="after")
    def _partes_en_acto_multiple(self) -> "ActoIn":
        if self.acto_multiple and self.mismas_partes is None:
            raise ValueError("Indicá si intervienen solo las mismas partes en la escritura.")
        return self

    @model_validator(mode="after")
    def _base_de_precio_o_avaluo(self) -> "ActoIn":
        base = base_de(self.precio, self.avaluo)
        if base is not None:
            if self.categoria is not CategoriaActo.ESCRITURA_CON_VALOR:
                raise ValueError("Solo un acto de aporte variable lleva precio o avalúo.")
            self.base_imponible = base
        return self

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
    matricula_numero: int | None
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
    vademecum_id: uuid.UUID | None
    vademecum_nombre: str | None
    fuera_de_vademecum: bool
    precio: Money | None
    avaluo: Money | None
    mismas_partes: bool
    # En borrador es el aporte estimado con los parámetros vigentes; presentada, el congelado.
    aporte: Money | None
    vigencia_id: uuid.UUID | None
    # Presentada: lo que aportaba solo, antes del criterio de pluralidad.
    aporte_individual: Money | None


class AporteActoOut(BaseModel):
    acto_id: uuid.UUID
    aporte: Money
    # Lo que aportaría solo. Mayor que `aporte` si quedó incluido en otro acto de su escritura.
    aporte_individual: Money
    incluido_en_otro: bool


class TramoMoraOut(BaseModel):
    """Días de atraso en que rigió una misma tasa (`desde` y `hasta` inclusive)."""

    desde: date
    hasta: date
    dias: int
    tasa: Rate
    periodo_tasa: PeriodoTasa
    interes: Money


class EscribanoBoletaOut(BaseModel):
    """De quién es la boleta y qué cobra."""

    id: uuid.UUID
    apellido_nombre: str
    cargo: Cargo
    modalidad: ModalidadBoleta


class LiquidacionBoletaOut(BaseModel):
    """La boleta que recibirá un escribano al presentar."""

    escribano: EscribanoBoletaOut
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


class LiquidacionOut(BaseModel):
    aportes: list[AporteActoOut]
    vencimiento: date
    fecha_pago: date
    # Una por escribano: cada uno paga la suya.
    boletas: list[LiquidacionBoletaOut]
    # Del registro: aportes de todos los actos y la suma de las boletas.
    total_protocolos: Money
    total_a_pagar: Money
    avisos: list[str]
    # Algún parámetro usado está marcado como ejemplo (no oficial).
    usa_valores_de_ejemplo: bool
    # Cómo aportan varios actos de una escritura con las mismas partes (None: aporta cada uno).
    criterio_pluralidad: CriterioPluralidad | None


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
    # Vacío en las boletas del registro (emitidas antes de las boletas por notario).
    escribano: EscribanoBoletaOut | None
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
    # Quien consulta puede emitir otra boleta de este escribano (la suya, o es de la Caja).
    puede_reemitir: bool = False


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
    precio: BaseImponible | None = None
    avaluo: BaseImponible | None = None
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
    # De quién es la boleta a reemitir. Vacío: la del registro (DDJJ anteriores a las boletas
    # por notario).
    escribano_id: uuid.UUID | None = None


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


class VademecumIn(BaseModel):
    """Versión nueva de un acto del vademécum (o su primera versión)."""

    codigo: CodigoVademecum
    nombre: NombreVademecum
    categoria: CategoriaActo
    motivo_exencion: MotivoExencion | None = None
    aclaracion: Texto | None = None
    sinonimos: Sinonimos | None = None
    orden: int = Field(default=0, ge=0, le=10_000)
    fecha_desde: date
    resolucion: Resolucion
    motivo: Motivo


class VademecumAprobacionIn(BaseModel):
    # Propuestas de otra persona a aprobar juntas (todas o ninguna).
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class VademecumRechazoIn(BaseModel):
    motivo: Motivo


class VademecumOut(BaseModel):
    id: uuid.UUID
    codigo: str
    version: int
    nombre: str
    categoria: CategoriaActo
    motivo_exencion: MotivoExencion | None
    aclaracion: str | None
    sinonimos: str | None
    orden: int
    fecha_desde: date
    fecha_hasta: date | None
    resolucion: str
    estado: EstadoVigencia
    created_by_user_id: uuid.UUID
    aprobado_por_user_id: uuid.UUID | None
    created_at: datetime
