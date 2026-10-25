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

    cuit: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(10), nullable=False, server_default="DNI")
    numero_documento: Mapped[str] = mapped_column(String(15), nullable=False)
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


class Escribano(UUIDMixin, TimestampMixin, AuthorMixin, Base):
    __tablename__ = "padron_escribanos"
    __table_args__ = (
        CheckConstraint("matricula_numero > 0", name="matricula_positiva"),
        CheckConstraint(
            "estado_matricula IN ('ACTIVO', 'SUSPENDIDO', 'CESANTE', 'JUBILADO', 'FALLECIDO')",
            name="estado_valido",
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
    matricula_numero: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    tomo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    folio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_matriculacion: Mapped[date] = mapped_column(Date, nullable=False)
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
