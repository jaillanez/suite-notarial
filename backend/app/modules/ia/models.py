"""Sugerencias de IA y su ratificación humana (reglas HIC y AUD).

Cada fila guarda qué propuso el motor (nombre, versión, confianza, campos con su respaldo y
alertas) y qué confirmó la persona, con los campos que corrigió. La propuesta nunca se modifica
y, una vez resuelta, la fila queda congelada (trigger `ia_sugerencias_guard`). Del documento de
entrada solo quedan metadatos y su SHA-256 (minimización de datos, Ley 25.326).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Sugerencia(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ia_sugerencias"
    __table_args__ = (
        CheckConstraint("tipo IN ('EXTRACCION_MINUTA', 'OCR_DNI')", name="tipo_valido"),
        CheckConstraint(
            "estado IN ('SUGERIDO_POR_IA', 'RATIFICADA', 'DESCARTADA')", name="estado_valido"
        ),
        CheckConstraint("confianza >= 0 AND confianza <= 1", name="confianza_rango"),
        CheckConstraint("tiempo_ms >= 0", name="tiempo"),
        CheckConstraint("tipo <> 'EXTRACCION_MINUTA' OR ddjj_id IS NOT NULL", name="minuta_ddjj"),
        CheckConstraint(
            "(estado = 'SUGERIDO_POR_IA') = (resuelto_por_user_id IS NULL AND resuelto_en IS NULL)",
            name="resolucion",
        ),
        # Human in Command: ratifica la misma persona que pidió y revisó la sugerencia, con los
        # datos que confirmó y el registro que efectivamente se creó.
        CheckConstraint(
            "estado <> 'RATIFICADA' OR (resuelto_por_user_id = solicitado_por_user_id "
            "AND datos_confirmados IS NOT NULL AND campos_modificados IS NOT NULL "
            "AND (acto_id IS NOT NULL OR escribano_id IS NOT NULL))",
            name="ratificacion_humana",
        ),
        CheckConstraint(
            "estado = 'RATIFICADA' OR (acto_id IS NULL AND escribano_id IS NULL "
            "AND datos_confirmados IS NULL)",
            name="destino_solo_ratificada",
        ),
        CheckConstraint("tipo = 'EXTRACCION_MINUTA' OR acto_id IS NULL", name="acto_de_minuta"),
        CheckConstraint("tipo = 'OCR_DNI' OR escribano_id IS NULL", name="escribano_de_dni"),
        Index("ix_ia_sugerencias_tipo_fecha", "tipo", "created_at"),
        Index("ix_ia_sugerencias_solicitante", "solicitado_por_user_id", "created_at"),
    )

    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="SUGERIDO_POR_IA"
    )
    motor: Mapped[str] = mapped_column(String(100), nullable=False)
    motor_version: Mapped[str] = mapped_column(String(20), nullable=False)
    tiempo_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    confianza: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    entrada: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    salida: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ddjj_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ddjj_declaraciones.id", ondelete="RESTRICT"), index=True
    )
    solicitado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id", ondelete="RESTRICT"), nullable=False
    )
    datos_confirmados: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    campos_modificados: Mapped[list[str] | None] = mapped_column(JSONB)
    # Diferidas: el registro de destino se inserta en la misma transacción que la ratificación.
    acto_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_actos.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        unique=True,
    )
    escribano_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "padron_escribanos.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"
        ),
        unique=True,
    )
    resuelto_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id", ondelete="RESTRICT")
    )
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_descarte: Mapped[str | None] = mapped_column(Text)
