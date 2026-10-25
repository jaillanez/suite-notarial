"""Comprobantes de pago y asientos de conciliación (Módulo 6).

- El escribano adjunta un comprobante a una boleta pendiente: queda PENDIENTE_REVISION.
- Tesorería lo aprueba o lo rechaza; cada decisión deja un asiento inmutable en
  `pagos_conciliaciones`. Recién con un asiento aprobado la boleta puede pasar a PAGADA (trigger).
- El archivo se guarda fuera del webroot con nombre UUID; acá quedan su tipo real, tamaño y huella.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin

MONEY = Numeric(15, 2)


class Comprobante(UUIDMixin, Base):
    __tablename__ = "pagos_comprobantes"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('PENDIENTE_REVISION', 'APROBADO', 'RECHAZADO')", name="estado_valido"
        ),
        CheckConstraint(
            "mime_type IN ('application/pdf', 'image/png', 'image/jpeg')", name="mime_permitido"
        ),
        CheckConstraint("tamano_bytes > 0 AND tamano_bytes <= 10485760", name="tamano"),
        CheckConstraint("importe_declarado > 0", name="importe"),
        CheckConstraint("(estado = 'RECHAZADO') = (motivo_rechazo IS NOT NULL)", name="motivo"),
        CheckConstraint(
            "(estado = 'PENDIENTE_REVISION') = (revisado_en IS NULL)", name="revision_coherente"
        ),
        # Un solo comprobante en revisión y uno solo aprobado por boleta.
        Index(
            "uq_pagos_comprobantes_en_revision",
            "boleta_id",
            unique=True,
            postgresql_where=text("estado = 'PENDIENTE_REVISION'"),
        ),
        Index(
            "uq_pagos_comprobantes_aprobado",
            "boleta_id",
            unique=True,
            postgresql_where=text("estado = 'APROBADO'"),
        ),
    )

    boleta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_boletas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_registros_notariales.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)

    # Archivo (regla MIME): tipo real por magic bytes, nombre UUID, huella para detectar cambios.
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    archivo: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Transferencia declarada por el escribano.
    fecha_transferencia: Mapped[date] = mapped_column(Date, nullable=False)
    banco_origen: Mapped[str | None] = mapped_column(String(100), nullable=True)
    numero_operacion: Mapped[str] = mapped_column(String(100), nullable=False)
    importe_declarado: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    estado: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="PENDIENTE_REVISION", index=True
    )
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)
    subido_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revisado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conciliacion(UUIDMixin, Base):
    """Asiento de Tesorería: inmutable (sin UPDATE ni DELETE para la aplicación)."""

    __tablename__ = "pagos_conciliaciones"
    __table_args__ = (
        CheckConstraint("resultado IN ('APROBADO', 'RECHAZADO')", name="resultado_valido"),
        CheckConstraint(
            "resultado <> 'APROBADO' OR (importe_confirmado > 0 "
            "AND fecha_acreditacion IS NOT NULL)",
            name="aprobado_completo",
        ),
        CheckConstraint(
            "resultado <> 'RECHAZADO' OR "
            "(importe_confirmado IS NULL AND observaciones IS NOT NULL)",
            name="rechazo_fundado",
        ),
    )

    comprobante_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pagos_comprobantes.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    boleta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_boletas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    importe_confirmado: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fecha_acreditacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    identificador_extracto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    operador_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    ip_operador: Mapped[str | None] = mapped_column(INET, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
