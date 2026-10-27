"""Declaraciones juradas, actos declarados, calendario de vencimientos y boletas (Módulo 5).

- Una DDJJ es por registro notarial y período (mes devengado). Reúne los actos de todos los
  escribanos del registro (titular, adscriptos, a cargo).
- Al presentarla se liquida en el servidor y se emite la boleta. Cada renglón y la boleta guardan
  el id de la vigencia paramétrica con que se calcularon (SNAP): cambiar parámetros no altera
  nada ya emitido.
- Nada liquidado se borra ni se modifica: un acto en borrador se da de baja con `is_active`, y
  una DDJJ presentada se corrige con una rectificativa.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

MONEY = Numeric(15, 2)
BASE = Numeric(18, 2)
RATE = Numeric(18, 4)
PERIODO_CHECK = "periodo ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'"


class Vencimiento(UUIDMixin, TimestampMixin, Base):
    """Fecha de vencimiento de la obligación de pago de cada período (calendario de la Caja)."""

    __tablename__ = "ddjj_vencimientos"
    __table_args__ = (CheckConstraint(PERIODO_CHECK, name="periodo_formato"),)

    periodo: Mapped[str] = mapped_column(String(7), unique=True, nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class DeclaracionJurada(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ddjj_declaraciones"
    __table_args__ = (
        CheckConstraint(PERIODO_CHECK, name="periodo_formato"),
        CheckConstraint(
            "estado IN ('BORRADOR', 'PRESENTADA', 'RECTIFICADA')", name="estado_valido"
        ),
        CheckConstraint("numero_rectificativa >= 0", name="rectificativa"),
        # Una sola DDJJ en curso (borrador o presentada) por registro y período.
        Index(
            "uq_ddjj_declaraciones_registro_periodo_vigente",
            "registro_id",
            "periodo",
            unique=True,
            postgresql_where=text("estado <> 'RECTIFICADA'"),
        ),
        Index(
            "uq_ddjj_declaraciones_registro_periodo_rect",
            "registro_id",
            "periodo",
            "numero_rectificativa",
            unique=True,
        ),
    )

    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_registros_notariales.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    numero_rectificativa: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="BORRADOR", index=True
    )
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_presentacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    presentada_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    rectifica_a_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ddjj_declaraciones.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )

    # Totales congelados al presentar.
    total_protocolos: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    cantidad_actos: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Acto(UUIDMixin, TimestampMixin, Base):
    """Renglón de la DDJJ: un acto autorizado por un escribano del registro."""

    __tablename__ = "ddjj_actos"
    __table_args__ = (
        CheckConstraint(
            "categoria IN ('ESCRITURA_CON_VALOR', 'ACTA_O_PODER', 'OTRO_ACTO', 'SIN_EFECTO')",
            name="categoria_valida",
        ),
        CheckConstraint("tipo_protocolo IN ('GENERAL', 'AUXILIAR')", name="protocolo"),
        CheckConstraint("numero_escritura > 0", name="numero"),
        CheckConstraint("folio IS NULL OR folio > 0", name="folio"),
        CheckConstraint("orden_en_escritura > 0", name="orden_en_escritura"),
        CheckConstraint("base_imponible >= 0", name="base"),
        CheckConstraint(
            "(categoria = 'ESCRITURA_CON_VALOR') = (base_imponible > 0)",
            name="base_segun_categoria",
        ),
        # Cada acto de una escritura es un renglón (aporte múltiple: varios actos en la misma
        # escritura, p. ej. venta de lotes a distintos compradores), numerado dentro de ella.
        Index(
            "uq_ddjj_actos_escritura",
            "ddjj_id",
            "tipo_protocolo",
            "numero_escritura",
            "orden_en_escritura",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    ddjj_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_declaraciones.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_escribanos.id", ondelete="RESTRICT"), nullable=False
    )
    cargo: Mapped[str] = mapped_column(String(30), nullable=False)
    tipo_protocolo: Mapped[str] = mapped_column(String(10), nullable=False)
    numero_escritura: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1 para el primer acto de la escritura; 2, 3… para los demás actos de la misma escritura.
    orden_en_escritura: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_acto: Mapped[date] = mapped_column(Date, nullable=False)
    naturaleza: Mapped[str] = mapped_column(String(300), nullable=False)
    categoria: Mapped[str] = mapped_column(String(30), nullable=False)
    base_imponible: Mapped[Decimal] = mapped_column(BASE, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )

    # Liquidación congelada al presentar (SNAP).
    aporte: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    vigencia_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_vigencias.id", ondelete="RESTRICT"),
        nullable=True,
    )

    escribano = relationship("Escribano", lazy="joined", innerjoin=True)


class Boleta(UUIDMixin, Base):
    """Boleta oficial de pago. Inmutable una vez emitida; solo cambia su estado."""

    __tablename__ = "ddjj_boletas"
    __table_args__ = (
        CheckConstraint(PERIODO_CHECK, name="periodo_formato"),
        CheckConstraint("estado IN ('PENDIENTE', 'PAGADA', 'ANULADA')", name="estado_valido"),
        CheckConstraint("fecha_pago >= fecha_emision", name="fecha_pago"),
        CheckConstraint(
            "dias_mora = 0 OR fecha_pago > fecha_vencimiento", name="mora_solo_fuera_de_termino"
        ),
        CheckConstraint("interes_mora = 0 OR dias_mora > 0", name="interes_con_mora"),
        CheckConstraint("total_a_pagar = total_en_termino + interes_mora", name="total_cuadra"),
        CheckConstraint(
            "total_en_termino = aporte_minimo + excedente + aporte_medico", name="termino_cuadra"
        ),
        # Una sola boleta pendiente por DDJJ.
        Index(
            "uq_ddjj_boletas_pendiente",
            "ddjj_id",
            unique=True,
            postgresql_where=text("estado = 'PENDIENTE'"),
        ),
    )

    numero: Mapped[int] = mapped_column(
        Integer,
        server_default=text("nextval('ddjj_boletas_numero_seq')"),
        unique=True,
        nullable=False,
    )
    codigo_verificacion: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    ddjj_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_declaraciones.id", ondelete="RESTRICT"),
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
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDIENTE", index=True
    )

    fecha_emision: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_pago: Mapped[date] = mapped_column(Date, nullable=False)
    dias_mora: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    total_protocolos: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    aporte_minimo: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    excedente: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    aporte_medico: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cantidad_aportes_medicos: Mapped[int] = mapped_column(Integer, nullable=False)
    total_en_termino: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    interes_mora: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_a_pagar: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    # Vigencias con que se calculó (SNAP).
    vigencia_minimo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_vigencias.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vigencia_medico_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_vigencias.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vigencia_mora_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_vigencias.id", ondelete="RESTRICT"),
        nullable=True,
    )

    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    emitida_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_anulacion: Mapped[str | None] = mapped_column(Text, nullable=True)
