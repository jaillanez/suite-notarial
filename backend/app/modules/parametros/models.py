"""Motor paramétrico: conceptos y vigencias versionadas (Módulo 4).

Una vigencia nueva es una fila nueva: los valores de una fila nunca cambian (trigger). La base
impide que dos vigencias VIGENTES del mismo concepto se superpongan (restricción de exclusión
sobre rangos de fechas). Las boletas guardan el id de la vigencia con que se calcularon (SNAP).
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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

MONEY = Numeric(15, 2)
RATE = Numeric(18, 4)


class Concepto(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "parametros_conceptos"
    __table_args__ = (
        CheckConstraint("codigo ~ '^[A-Z][A-Z0-9_]{2,49}$'", name="codigo_formato"),
        CheckConstraint(
            "tipo IN ('PORCENTUAL_ACTO', 'FIJO_ACTO', 'FIJO_MENSUAL', 'TASA_MORA')",
            name="tipo_valido",
        ),
    )

    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class Vigencia(UUIDMixin, Base):
    __tablename__ = "parametros_vigencias"
    __table_args__ = (
        CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="rango_valido"),
        CheckConstraint(
            "estado IN ('PENDIENTE_APROBACION', 'VIGENTE', 'RECHAZADA', 'RETIRADA')",
            name="estado_valido",
        ),
        CheckConstraint("regla_redondeo IN ('HALF_UP', 'FLOOR', 'CEILING')", name="redondeo"),
        CheckConstraint(
            "porcentaje IS NULL OR (porcentaje >= 0 AND porcentaje <= 100)", name="pct"
        ),
        CheckConstraint("monto_fijo IS NULL OR monto_fijo >= 0", name="fijo"),
        CheckConstraint("monto_minimo IS NULL OR monto_minimo >= 0", name="minimo"),
        CheckConstraint(
            "monto_maximo IS NULL OR monto_maximo >= COALESCE(monto_minimo, 0)", name="maximo"
        ),
        CheckConstraint("tasa IS NULL OR (tasa >= 0 AND tasa <= 100)", name="tasa"),
        CheckConstraint(
            "dias_gracia IS NULL OR (dias_gracia >= 0 AND dias_gracia <= 90)", name="gracia"
        ),
        CheckConstraint(
            "periodo_tasa IS NULL OR periodo_tasa IN ('MENSUAL', 'ANUAL')", name="periodo_tasa"
        ),
        CheckConstraint("(tasa IS NULL) = (periodo_tasa IS NULL)", name="tasa_con_periodo"),
        CheckConstraint(
            "(estado = 'VIGENTE') = (aprobado_por_user_id IS NOT NULL)", name="aprobacion"
        ),
        CheckConstraint(
            "aprobado_por_user_id IS NULL OR aprobado_por_user_id <> created_by_user_id",
            name="cuatro_ojos",
        ),
        Index("uq_parametros_vigencias_concepto_version", "concepto_id", "version", unique=True),
        # La restricción de exclusión sin solapamiento (GiST sobre daterange) vive en la migración
        # fase3_parametros: SQLAlchemy no la modela.
    )

    concepto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_conceptos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Valores. Los porcentajes se expresan en % (4.0000 = 4 %); los montos en pesos.
    porcentaje: Mapped[Decimal | None] = mapped_column(RATE, nullable=True)
    monto_fijo: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    monto_minimo: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    monto_maximo: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Tasa de mora en %, expresada en la unidad de `periodo_tasa` (mensual o anual).
    tasa: Mapped[Decimal | None] = mapped_column(RATE, nullable=True)
    periodo_tasa: Mapped[str | None] = mapped_column(String(10), nullable=True)
    dias_gracia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regla_redondeo: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="HALF_UP"
    )

    # Valor cargado como ejemplo de desarrollo, no oficial. TODO(negocio): reemplazar por los
    # valores aprobados por la Caja antes de producción.
    es_ejemplo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    estado: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="PENDIENTE_APROBACION", index=True
    )
    resolucion_respaldo: Mapped[str] = mapped_column(String(100), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    aprobado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    fecha_aprobacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rechazada_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)

    # INNER JOIN: el concepto es obligatorio, y permite SELECT ... FOR UPDATE de la vigencia.
    concepto: Mapped[Concepto] = relationship(lazy="joined", innerjoin=True)
