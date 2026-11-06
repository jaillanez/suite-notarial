"""Padrón notarial: personas, escribanos, registros, cargos y circunscripciones (Módulo 3).

Regla INM: ninguna fila se borra. Las bajas son cambios de estado o cierres con fecha, y el
rol de la aplicación no tiene DELETE sobre estas tablas (ver migración fase2_padron).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class AuthorMixin:
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class Circunscripcion(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    __tablename__ = "padron_circunscripciones"

    nombre: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Persona(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    """Datos personales y fiscales: viven solo acá (USR-01)."""

    __tablename__ = "padron_personas"
    __table_args__ = (
        CheckConstraint("cuit ~ '^[0-9]{11}$'", name="cuit_digits"),
        Index("ix_padron_personas_apellido_nombre", "apellido", "nombre"),
    )

    # CUIT y documento pueden faltar en personas migradas del sistema anterior (históricos sin
    # esos datos): quedan «a completar». El alta manual los exige. UNIQUE admite varios NULL.
    cuit: Mapped[str | None] = mapped_column(String(11), unique=True, nullable=True)
    tipo_documento: Mapped[str] = mapped_column(String(10), nullable=False, server_default="DNI")
    numero_documento: Mapped[str | None] = mapped_column(String(15), nullable=True)
    apellido: Mapped[str] = mapped_column(String(100), nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(50), nullable=True)
    domicilio_real: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegistroNotarial(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    __tablename__ = "padron_registros_notariales"
    __table_args__ = (
        CheckConstraint("numero_registro > 0", name="numero_positivo"),
        CheckConstraint("estado IN ('ACTIVO', 'VACANTE', 'CERRADO')", name="estado_valido"),
    )

    numero_registro: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    nombre_fantasia: Mapped[str | None] = mapped_column(String(150), nullable=True)
    circunscripcion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_circunscripciones.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    departamento: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    domicilio_legal: Mapped[str] = mapped_column(Text, nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_creacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="VACANTE", index=True
    )

    circunscripcion: Mapped[Circunscripcion] = relationship(lazy="joined")


class DomicilioRegistro(UUIDMixin, Base):
    """Historia del domicilio de un registro. `RegistroNotarial.domicilio_legal` conserva el
    vigente (compatibilidad); todo cambio pasa por el servicio, que cierra la fila vigente y
    abre una nueva. Nunca se borra. Sin solapamiento por registro (exclusión GiST en la
    migración padron_ajustes_caja)."""

    __tablename__ = "padron_registro_domicilios"
    __table_args__ = (
        CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="fechas"),
        # Un solo domicilio vigente por registro.
        Index(
            "uq_padron_registro_domicilios_vigente",
            "registro_id",
            unique=True,
            postgresql_where=text("fecha_hasta IS NULL"),
        ),
    )

    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_registros_notariales.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    domicilio: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Ordena los INSERT (registro antes que su domicilio) cuando van en el mismo flush.
    registro: Mapped[RegistroNotarial] = relationship(lazy="raise")


class Escribano(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    __tablename__ = "padron_escribanos"
    __table_args__ = (
        CheckConstraint("matricula_numero > 0", name="matricula_positiva"),
        CheckConstraint(
            "estado_matricula IN ('ACTIVO', 'SUSPENDIDO', 'CESANTE', 'JUBILADO', 'FALLECIDO')",
            name="estado_valido",
        ),
        # La primera escritura se carga completa (fecha, número y registro) o no se carga.
        CheckConstraint(
            "(primera_escritura_fecha IS NULL) = (primera_escritura_numero IS NULL) AND "
            "(primera_escritura_fecha IS NULL) = (primera_escritura_registro IS NULL)",
            name="primera_escritura_completa",
        ),
        CheckConstraint(
            "primera_escritura_registro IS NULL OR primera_escritura_registro > 0",
            name="primera_escritura_registro_positivo",
        ),
    )

    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_personas.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    # Cuenta de autogestión del escribano (opcional).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("security_users.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    # La matrícula NO identifica al escribano (decisión de la Caja): el Colegio puede reasignar
    # el número de un escribano retirado a uno nuevo. Es un dato informativo, sin unicidad; lo
    # que identifica es el CUIT de la persona. Puede faltar en escribanos migrados («a
    # completar»); el CHECK de positividad pasa con NULL.
    matricula_numero: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    tomo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    folio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Fecha de juramento (la columna conserva su nombre histórico `fecha_matriculacion`). Puede
    # faltar en escribanos migrados: queda «a completar».
    fecha_matriculacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Primera escritura autorizada: determina la antigüedad para la jubilación. La Caja recibe
    # la escritura después de la afiliación, así que se carga más tarde (y se puede corregir,
    # con auditoría). El registro es un número, no una FK: puede ser un registro que ya no
    # existe. TODO(negocio): reglas de antigüedad para la jubilación (no se implementan acá).
    primera_escritura_fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    primera_escritura_numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    primera_escritura_registro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primera_escritura_folio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    primera_escritura_cargada_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    primera_escritura_cargada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    estado_matricula: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="ACTIVO", index=True
    )
    motivo_ultimo_cambio_estado: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_ultimo_cambio_estado: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    persona: Mapped[Persona] = relationship(lazy="joined")


class Adscripcion(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    """Cargo de un escribano en un registro. Se cierra con fecha; nunca se borra."""

    __tablename__ = "padron_adscripciones"
    __table_args__ = (
        CheckConstraint(
            "cargo IN ('TITULAR', 'ADSCRIPTO', 'SUPLENTE_INTERINO')", name="cargo_valido"
        ),
        CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="fechas"),
        CheckConstraint("is_current = (fecha_hasta IS NULL)", name="vigencia_coherente"),
        # Un solo titular vigente por registro.
        Index(
            "uq_padron_adscripciones_titular_vigente",
            "registro_id",
            unique=True,
            postgresql_where=text("is_current AND cargo = 'TITULAR'"),
        ),
        # Un solo cargo vigente por escribano.
        Index(
            "uq_padron_adscripciones_cargo_vigente",
            "escribano_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_registros_notariales.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cargo: Mapped[str] = mapped_column(String(30), nullable=False)
    resolucion_designacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo_cierre: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    escribano: Mapped[Escribano] = relationship(lazy="joined")
    registro: Mapped[RegistroNotarial] = relationship(lazy="joined")


class HistorialEstado(UUIDMixin, Base):
    """Historial inmutable de cambios de estado de matrícula (DIR-02)."""

    __tablename__ = "padron_historial_estados"

    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    estado_anterior: Mapped[str] = mapped_column(String(30), nullable=False)
    estado_nuevo: Mapped[str] = mapped_column(String(30), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    resolucion_respaldo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_efectiva: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_cambio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    operador_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )


class DesignacionACargo(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    """Escribano a cargo de un registro entre dos fechas (licencia o ausencia del titular).

    Convive con el cargo propio del designado: el titular de un registro de Jáchal puede quedar
    a cargo de uno de Capital. Solo una designación APROBADA habilita a operar el registro, y
    solo entre `fecha_desde` y `fecha_hasta` (inclusive). Nunca se borra: se anula o se termina
    antes con motivo.
    """

    __tablename__ = "padron_designaciones_a_cargo"
    __table_args__ = (
        CheckConstraint("fecha_hasta >= fecha_desde", name="fechas"),
        CheckConstraint(
            "estado IN ('PENDIENTE', 'APROBADA', 'RECHAZADA', 'ANULADA')", name="estado_valido"
        ),
        CheckConstraint(
            "estado NOT IN ('RECHAZADA', 'ANULADA') OR motivo_resolucion IS NOT NULL",
            name="baja_con_motivo",
        ),
    )

    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_registros_notariales.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    # Quién aprobó, rechazó o anuló, cuándo y por qué (una aprobación por aviso no lo lleva).
    resuelta_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    resuelta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_resolucion: Mapped[str | None] = mapped_column(Text, nullable=True)

    escribano: Mapped[Escribano] = relationship(lazy="joined")
    registro: Mapped[RegistroNotarial] = relationship(lazy="joined")


class AjustesPadron(Base):
    """Ajustes del padrón que decide la Caja (una sola fila)."""

    __tablename__ = "padron_ajustes"
    __table_args__ = (CheckConstraint("id = 1", name="fila_unica"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="1")
    # Con True, la designación de un escribano a cargo que carga el titular espera la
    # aprobación de la Caja; con False, rige al cargarla y la Caja queda avisada.
    a_cargo_requiere_aprobacion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class Licencia(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    """Licencia de un escribano: deja de ejercer un tiempo y vuelve; su cargo sigue siendo suyo.

    No cambia el estado de la matrícula ni cierra cargos. `fecha_hasta` NULL = vigente. No se
    borra: se termina (fecha_hasta) o se anula con motivo. Sin solapamiento entre licencias no
    anuladas del mismo escribano (exclusión GiST en la migración padron_ajustes_caja).
    """

    __tablename__ = "padron_licencias"
    __table_args__ = (
        CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="fechas"),
        CheckConstraint(
            "NOT anulada OR (motivo_anulacion IS NOT NULL AND anulada_en IS NOT NULL)",
            name="anulacion_con_motivo",
        ),
    )

    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    resolucion_respaldo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    anulada: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    motivo_anulacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    anulada_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
