"""Contratos del padrón notarial."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.common.cuit import InvalidCuitError, normalize_cuit
from app.modules.padron.catalog import (
    DEPARTAMENTOS_SAN_JUAN,
    AporteACargo,
    Cargo,
    EstadoDesignacion,
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
    # None: migrada sin CUIT o sin documento («a completar»).
    cuit: str | None
    tipo_documento: str
    numero_documento: str | None
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
    matricula_numero: int | None
    apellido_nombre: str
    cargo: Cargo
    fecha_desde: date | None  # None: «a completar» (migrado sin fecha)
    estado_matricula: EstadoMatricula


class RegistroOut(BaseModel):
    id: uuid.UUID
    numero_registro: int
    nombre_fantasia: str | None
    circunscripcion: CircunscripcionOut
    departamento: str | None  # None: «a completar» (migrado sin departamento)
    domicilio_legal: str
    telefono: str | None
    email: str | None
    fecha_creacion: date | None
    estado: EstadoRegistro
    titular: CargoResumen | None = None
    cantidad_adscriptos: int = 0


class DomicilioCambio(BaseModel):
    """Nuevo domicilio del registro: cierra el vigente el día anterior a `fecha_desde`."""

    domicilio: Texto
    fecha_desde: date


class DomicilioOut(BaseModel):
    id: uuid.UUID
    domicilio: str
    fecha_desde: date
    # None: vigente.
    fecha_hasta: date | None
    cargado_por: str | None
    created_at: datetime


class RegistroDetalle(RegistroOut):
    cargos_vigentes: list[CargoResumen]
    # Historia del domicilio, del más reciente al más antiguo.
    domicilios: list[DomicilioOut] = []


# --------------------------------------------------------------------------- escribanos


Corto20 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class EscribanoIn(BaseModel):
    persona: PersonaIn
    # Dato informativo: no identifica (el Colegio puede reasignarla). Identifica el CUIT.
    matricula_numero: int = Field(gt=0, lt=1_000_000)
    tomo: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    folio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    # Fecha de juramento (el campo conserva su nombre histórico).
    fecha_matriculacion: date = Field(description="Fecha de juramento.")


class PrimeraEscrituraDatos(BaseModel):
    """Primera escritura autorizada: determina la antigüedad para la jubilación."""

    fecha: date
    numero: Corto20
    # Número de registro (no tiene que existir en la Suite: puede ser uno ya cerrado).
    registro: int = Field(gt=0, lt=100_000)
    folio: Corto20 | None = None


class PrimeraEscrituraIn(PrimeraEscrituraDatos):
    """Carga o corrección. Corregir una ya cargada exige motivo (queda auditado)."""

    motivo: Motivo | None = None


class PrimeraEscrituraOut(BaseModel):
    fecha: date
    numero: str
    registro: int
    folio: str | None
    cargada_por: str | None
    cargada_en: datetime | None


class AntiguedadOut(BaseModel):
    """Tiempo transcurrido desde la primera escritura hasta hoy.

    TODO(negocio): las reglas de antigüedad para la jubilación (licencias, interrupciones) no
    están definidas; esto es el cálculo calendario, informativo.
    """

    desde: date
    anios: int
    meses: int


class EscribanoUpdate(BaseModel):
    tomo: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    folio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    fecha_matriculacion: date | None = None
    persona: PersonaUpdate | None = None


class DatosACompletar(BaseModel):
    """Datos que faltaban al migrar del sistema anterior. Se cargan una sola vez: cada campo
    enviado tiene que estar hoy vacío (cambiar uno ya cargado no se hace por acá; la primera
    escritura se corrige desde su propia acción, con motivo)."""

    matricula_numero: int | None = Field(default=None, gt=0, lt=1_000_000)
    fecha_matriculacion: date | None = Field(default=None, description="Fecha de juramento.")
    cuit: str | None = None
    numero_documento: Documento | None = None
    primera_escritura: PrimeraEscrituraDatos | None = None

    @field_validator("cuit")
    @classmethod
    def _v_cuit(cls, value: str | None) -> str | None:
        return None if value is None else _cuit(value)

    @model_validator(mode="after")
    def _alguno(self) -> "DatosACompletar":
        if all(getattr(self, f) is None for f in type(self).model_fields):
            raise ValueError("Indicá al menos un dato a completar.")
        return self


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


class CargoFechaDesde(BaseModel):
    """Fecha de designación de un cargo migrado sin ella: se carga una sola vez."""

    fecha_desde: date


class CargoCierre(BaseModel):
    fecha_hasta: date
    motivo: Motivo


class CargoOut(BaseModel):
    id: uuid.UUID
    registro_id: uuid.UUID
    numero_registro: int
    cargo: Cargo
    resolucion_designacion: str | None
    fecha_desde: date | None  # None: «a completar» (migrado sin fecha)
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


class LicenciaIn(BaseModel):
    fecha_desde: date
    # None: sin fecha de regreso (vigente hasta que se la termine).
    fecha_hasta: date | None = None
    motivo: Motivo
    resolucion_respaldo: Corto | None = None

    @model_validator(mode="after")
    def _fechas(self) -> "LicenciaIn":
        if self.fecha_hasta is not None and self.fecha_hasta < self.fecha_desde:
            raise ValueError("La fecha de regreso no puede ser anterior al inicio de la licencia.")
        return self


class LicenciaFin(BaseModel):
    """Termina la licencia: el escribano vuelve a ejercer después de `fecha_hasta`."""

    fecha_hasta: date


class LicenciaAnulacion(BaseModel):
    motivo: Motivo


class LicenciaOut(BaseModel):
    id: uuid.UUID
    fecha_desde: date
    fecha_hasta: date | None
    motivo: str
    resolucion_respaldo: str | None
    anulada: bool
    motivo_anulacion: str | None
    anulada_en: datetime | None
    # No anulada y con la fecha de hoy dentro del rango.
    vigente: bool
    cargada_por: str | None
    created_at: datetime


class DesignacionResumen(BaseModel):
    """Designación del escribano a cargo de un registro (convive con su cargo propio)."""

    id: uuid.UUID
    registro_id: uuid.UUID
    numero_registro: int
    fecha_desde: date
    fecha_hasta: date
    estado: EstadoDesignacion
    motivo: str


class EscribanoOut(BaseModel):
    id: uuid.UUID
    # None: dato que faltaba en el sistema anterior («a completar»). Informativa: no es única.
    matricula_numero: int | None
    tomo: str | None
    folio: str | None
    # Fecha de juramento (el campo conserva su nombre histórico).
    fecha_matriculacion: date | None = Field(description="Fecha de juramento.")
    estado_matricula: EstadoMatricula
    apellido_nombre: str
    cuit: str | None
    numero_documento: str | None
    registro_actual: int | None
    cargo_actual: Cargo | None
    tiene_cuenta: bool
    # Inicio de la licencia vigente hoy (None: no está de licencia).
    en_licencia_desde: date | None = None


class EscribanoDetalle(EscribanoOut):
    persona: PersonaOut
    transiciones_permitidas: list[EstadoMatricula]
    transiciones_con_resolucion: list[EstadoMatricula]
    motivo_ultimo_cambio_estado: str | None
    fecha_ultimo_cambio_estado: datetime | None
    # Datos que faltaban al migrar y se pueden completar una vez.
    a_completar: list[str]
    # Historia completa de cargos (titular / adscripto por registro), del más reciente al más
    # antiguo, vigentes y cerrados.
    cargos: list[CargoOut]
    historial: list[HistorialOut]
    primera_escritura: PrimeraEscrituraOut | None = None
    # None: falta la primera escritura («a completar»).
    antiguedad: AntiguedadOut | None = None
    licencias: list[LicenciaOut] = []
    designaciones_a_cargo: list[DesignacionResumen] = []


class CuentaIn(BaseModel):
    """El operador confirma el correo: debe coincidir con el registrado en el padrón."""

    email: EmailStr


# --------------------------------------------------------------------------- escribano a cargo


class DesignacionIn(BaseModel):
    registro_id: uuid.UUID
    escribano_id: uuid.UUID
    fecha_desde: date
    fecha_hasta: date
    motivo: Motivo

    @model_validator(mode="after")
    def _fechas(self) -> "DesignacionIn":
        if self.fecha_hasta < self.fecha_desde:
            raise ValueError("La fecha hasta no puede ser anterior a la fecha desde.")
        return self


class DesignacionAporteIn(BaseModel):
    """Qué paga el escribano a cargo por los actos del registro (lo fija la Caja)."""

    aporte: AporteACargo
    motivo: Motivo


class DesignacionBaja(BaseModel):
    """Rechazo o anulación: siempre con motivo."""

    motivo: Motivo


class DesignacionTermino(BaseModel):
    """Adelanta el fin de una designación aprobada (p. ej. el titular volvió antes)."""

    fecha_hasta: date
    motivo: Motivo


class DesignacionOut(BaseModel):
    id: uuid.UUID
    registro_id: uuid.UUID
    numero_registro: int
    departamento: str | None
    escribano_id: uuid.UUID
    apellido_nombre: str
    matricula_numero: int | None
    fecha_desde: date
    fecha_hasta: date
    motivo: str
    estado: EstadoDesignacion
    # Qué paga por los actos del registro (solo el personal de la Caja lo cambia).
    aporte: AporteACargo
    # Aprobada y con la fecha de hoy dentro del rango.
    rige_hoy: bool
    created_at: datetime
    # Correos de quien cargó y quien resolvió: solo para el personal de la Caja.
    cargada_por: str | None
    resuelta_por: str | None
    resuelta_en: datetime | None
    motivo_resolucion: str | None
    # Acciones que puede hacer quien consulta.
    puede_aprobar: bool
    puede_anular: bool
    puede_terminar: bool
    puede_fijar_aporte: bool


class AjustesPadronIn(BaseModel):
    a_cargo_requiere_aprobacion: bool


class AjustesPadronOut(BaseModel):
    a_cargo_requiere_aprobacion: bool
    updated_at: datetime | None
    puede_editar: bool


class EscribanoElegible(BaseModel):
    """Escribano activo que puede quedar a cargo (cualquiera de la provincia)."""

    id: uuid.UUID
    apellido_nombre: str
    matricula_numero: int | None
    numero_registro: int | None
    departamento: str | None


class RegistroGestionable(BaseModel):
    """Registro en el que quien consulta puede designar un escribano a cargo."""

    id: uuid.UUID
    numero_registro: int
    departamento: str | None
