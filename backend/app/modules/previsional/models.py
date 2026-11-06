"""Ejercicios previsionales y puntos por afiliado (reglamentación de la Ley 7231).

El ejercicio va del 1 de septiembre al 31 de agosto y se nombra por el año de cierre: «1990»
es del 01/09/1989 al 31/08/1990. Los puntos determinan los beneficios previsionales.

Regla INM: ninguna fila se borra ni se reescribe. Un ejercicio cargado no cambia; de los puntos
solo cambia el vínculo con el padrón (escribano, forma de vínculo, quién y cuándo, sugerencia),
y ese cambio queda auditado. Lo garantiza el trigger `previsional_guard` (migración
puntos_ley_7231).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Ejercicio(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "previsional_ejercicios"
    __table_args__ = (
        CheckConstraint("anio BETWEEN 1900 AND 2200", name="anio_valido"),
        CheckConstraint("fecha_cierre > fecha_inicio", name="fechas"),
        CheckConstraint("cantidad_afiliados >= 0", name="cantidad_no_negativa"),
    )

    anio: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_cierre: Mapped[date] = mapped_column(Date, nullable=False)
    total_aportes: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    cantidad_afiliados: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    aporte_medio: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    origen: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )


class PuntosAfiliado(UUIDMixin, TimestampMixin, Base):
    """Aportes y puntos de un afiliado en un ejercicio, tal como figuran en el origen."""

    __tablename__ = "previsional_puntos"
    __table_args__ = (
        UniqueConstraint("ejercicio_id", "nombre_origen", name="uq_previsional_puntos_nombre"),
        CheckConstraint(
            "vinculacion IS NULL OR vinculacion IN ('EXACTA', 'HEREDADA', 'MANUAL')",
            name="vinculacion_valida",
        ),
        CheckConstraint("(escribano_id IS NULL) = (vinculacion IS NULL)", name="vinculo_coherente"),
        # MANUAL = una persona, siempre con autor; EXACTA y HEREDADA son automáticas, sin autor.
        CheckConstraint(
            "(vinculacion = 'MANUAL') = (vinculado_por_user_id IS NOT NULL)",
            name="manual_con_autor",
        ),
        # Una sugerencia solo existe mientras la fila no tiene escribano.
        CheckConstraint(
            "escribano_sugerido_id IS NULL OR escribano_id IS NULL", name="sugerencia_sin_vinculo"
        ),
        CheckConstraint("aportes <> 0 OR puntos <> 0", name="no_vacia"),
    )

    ejercicio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("previsional_ejercicios.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    escribano_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Nombre tal como figura en la planilla (clave para vincular y para recargar sin duplicar).
    nombre_origen: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    aportes: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    puntos: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    origen: Mapped[str] = mapped_column(Text, nullable=False)
    # Fila de la planilla (1 = primera), para revisar contra el original.
    fila_origen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vinculacion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vinculado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    vinculado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Coincidencia aproximada: solo la usa la cola de revisión. NO atribuye los puntos.
    escribano_sugerido_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Sugerencia que una persona rechazó: no se vuelve a proponer al revincular.
    sugerencia_rechazada_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_escribanos.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
