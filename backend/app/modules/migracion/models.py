"""Corridas de migración, su trazabilidad y el histórico de solo lectura.

- `migracion_corridas`: cada simulacro o carga definitiva, con el informe de cuadratura.
- `migracion_observaciones`: problemas de calidad por fila (sin datos personales).
- `migracion_mapeo`: código del sistema anterior → id en la Suite (solo carga definitiva).
- `migracion_conformidades`: firma de Tesorería y de Caja sobre un simulacro.
- `historico_boletas` / `historico_pagos`: boletas y pagos del sistema anterior. No se
  transforman en boletas de la Suite (no tienen vigencia paramétrica ni conciliación: serían
  asientos ficticios); se conservan tal cual, de solo lectura, para saldos y consultas.

Todo es inmutable por trigger; el histórico solo admite INSERT dentro de una carga de migración
(`SET LOCAL suite.migracion = 'on'`).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Corrida(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "migracion_corridas"
    __table_args__ = (
        CheckConstraint("modo IN ('SIMULACRO', 'DEFINITIVA')", name="modo_valido"),
        CheckConstraint(
            "estado IN ('EN_CURSO', 'SIMULADA', 'CARGADA', 'FALLIDA')", name="estado_valido"
        ),
        CheckConstraint("estado <> 'SIMULADA' OR modo = 'SIMULACRO'", name="simulada"),
        CheckConstraint("estado <> 'CARGADA' OR modo = 'DEFINITIVA'", name="cargada"),
        CheckConstraint("(estado = 'EN_CURSO') = (finalizada_en IS NULL)", name="finalizacion"),
        # Una sola carga definitiva por base.
        Index(
            "uq_migracion_corridas_definitiva",
            "modo",
            unique=True,
            postgresql_where=text("modo = 'DEFINITIVA' AND estado IN ('EN_CURSO', 'CARGADA')"),
        ),
    )

    modo: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="EN_CURSO")
    huella_lote: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_formato: Mapped[str] = mapped_column(String(10), nullable=False)
    homologacion: Mapped[str] = mapped_column(String(200), nullable=False)
    homologacion_ejemplo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # La tabla de homologación usada (huella y contenido: códigos, sin datos personales). La
    # conformidad de un simulacro cubre lote y tabla; la definitiva exige ambos iguales.
    huella_homologacion: Mapped[str] = mapped_column(String(64), nullable=False)
    homologacion_tablas: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operador_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id", ondelete="RESTRICT"), nullable=False
    )
    finalizada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cuadra: Mapped[bool | None] = mapped_column(Boolean)
    bloqueantes: Mapped[int | None] = mapped_column(Integer)
    advertencias: Mapped[int | None] = mapped_column(Integer)
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
    # Cuadratura y resumen: totales y conteos, sin datos personales.
    informe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class ObservacionMigracion(UUIDMixin, Base):
    __tablename__ = "migracion_observaciones"
    __table_args__ = (
        CheckConstraint("severidad IN ('BLOQUEANTE', 'ADVERTENCIA')", name="severidad_valida"),
        Index("ix_migracion_observaciones_corrida", "corrida_id", "entidad", "fila"),
    )

    corrida_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("migracion_corridas.id", ondelete="RESTRICT"), nullable=False
    )
    entidad: Mapped[str] = mapped_column(String(20), nullable=False)
    # Línea del archivo (0: observación de conjunto, p. ej. coherencia boleta/pagos).
    fila: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo_legado: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severidad: Mapped[str] = mapped_column(String(20), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)


class Mapeo(UUIDMixin, Base):
    __tablename__ = "migracion_mapeo"
    __table_args__ = (
        UniqueConstraint("entidad", "codigo_legado", name="uq_migracion_mapeo_codigo"),
        UniqueConstraint("entidad", "destino_id", name="uq_migracion_mapeo_destino"),
    )

    corrida_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("migracion_corridas.id", ondelete="RESTRICT"), nullable=False
    )
    entidad: Mapped[str] = mapped_column(String(20), nullable=False)
    codigo_legado: Mapped[str] = mapped_column(String(100), nullable=False)
    destino_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class Conformidad(UUIDMixin, Base):
    __tablename__ = "migracion_conformidades"
    __table_args__ = (
        CheckConstraint("area IN ('TESORERIA', 'CAJA')", name="area_valida"),
        UniqueConstraint("corrida_id", "area", name="uq_migracion_conformidades_area"),
        # Tesorería y Caja firman personas distintas.
        UniqueConstraint("corrida_id", "user_id", name="uq_migracion_conformidades_persona"),
    )

    corrida_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("migracion_corridas.id", ondelete="RESTRICT"), nullable=False
    )
    area: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id", ondelete="RESTRICT"), nullable=False
    )
    observaciones: Mapped[str | None] = mapped_column(Text)
    firmada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class HistoricoBoleta(UUIDMixin, Base):
    __tablename__ = "historico_boletas"
    __table_args__ = (
        CheckConstraint("estado IN ('IMPAGA', 'PAGADA', 'ANULADA')", name="estado_valido"),
        CheckConstraint("importe >= 0", name="importe"),
        Index("ix_historico_boletas_registro_periodo", "registro_id", "periodo"),
        Index("ix_historico_boletas_estado_vencimiento", "estado", "fecha_vencimiento"),
    )

    corrida_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("migracion_corridas.id", ondelete="RESTRICT"), nullable=False
    )
    codigo_legado: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_registros_notariales.id", ondelete="RESTRICT"),
        nullable=False,
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)
    numero_boleta: Mapped[str | None] = mapped_column(String(50))
    fecha_emision: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    importe: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class HistoricoPago(UUIDMixin, Base):
    __tablename__ = "historico_pagos"
    __table_args__ = (CheckConstraint("importe > 0", name="importe"),)

    corrida_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("migracion_corridas.id", ondelete="RESTRICT"), nullable=False
    )
    codigo_legado: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    boleta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("historico_boletas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fecha_pago: Mapped[date] = mapped_column(Date, nullable=False)
    importe: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    medio: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
