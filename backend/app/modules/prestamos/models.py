"""Líneas de crédito, préstamos y su plan de cuotas (Módulo 9).

- Las líneas son parámetros del Directorio. Cambiarlas no altera préstamos otorgados: cada
  préstamo guarda tasa, sistema, plazo y la evaluación con que se otorgó (SNAP).
- El plan de cuotas se genera al otorgar y es inmutable (trigger): solo cambia el estado de pago
  de cada cuota. Nada se borra (INM).
- Quien carga la solicitud no puede otorgarla (cuatro ojos, también como CHECK).
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

MONEY = Numeric(15, 2)
RATE = Numeric(18, 4)
MONEDA_VALIDA = "moneda IN ('ARS', 'USD')"


class Linea(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "prestamos_lineas"
    __table_args__ = (
        CheckConstraint("codigo ~ '^[A-Z][A-Z0-9_]{2,49}$'", name="codigo_formato"),
        CheckConstraint("sistema IN ('FRANCES', 'ALEMAN')", name="sistema"),
        CheckConstraint("plazo_minimo > 0 AND plazo_maximo >= plazo_minimo", name="plazos"),
        CheckConstraint("plazo_maximo <= 360", name="plazo_tope"),
        CheckConstraint("monto_minimo > 0 AND monto_maximo >= monto_minimo", name="montos"),
        CheckConstraint("tna >= 0 AND tna <= 1000", name="tna"),
        CheckConstraint("afectacion_maxima > 0 AND afectacion_maxima <= 100", name="afectacion"),
        CheckConstraint(MONEDA_VALIDA, name="moneda"),
        CheckConstraint(
            "relacion_capital_hipoteca IS NULL OR "
            "(relacion_capital_hipoteca > 0 AND relacion_capital_hipoteca <= 100)",
            name="relacion_capital_hipoteca",
        ),
        CheckConstraint(
            "antiguedad_minima_meses IS NULL OR antiguedad_minima_meses > 0",
            name="antiguedad_minima",
        ),
    )

    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    sistema: Mapped[str] = mapped_column(String(10), nullable=False)
    plazo_minimo: Mapped[int] = mapped_column(Integer, nullable=False)
    plazo_maximo: Mapped[int] = mapped_column(Integer, nullable=False)
    monto_minimo: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    monto_maximo: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Tasa nominal anual en % (42.0000 = 42 %).
    tna: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    # Tope de la cuota sobre el ingreso neto mensual, en % (30.0000 = 30 %).
    afectacion_maxima: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    requiere_garante: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Moneda de los montos de la línea y de sus préstamos (catalog.Moneda).
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, server_default="ARS")
    # Requisitos de la línea (Resolución N° 273). Informativos salvo la antigüedad, que se
    # controla al evaluar cuando se conoce la fecha de juramento.
    garantia: Mapped[str | None] = mapped_column(Text, nullable=True)
    requisito_conducta: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Capital sobre el valor del inmueble hipotecado, en % (70.0000 = 70 %).
    relacion_capital_hipoteca: Mapped[Decimal | None] = mapped_column(RATE, nullable=True)
    requiere_certificado_ingresos: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    requiere_certificado_bienes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    antiguedad_minima_meses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Valores de ejemplo, no aprobados por el Directorio: se muestran como "A confirmar".
    es_ejemplo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class Prestamo(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "prestamos"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('SOLICITADO', 'OTORGADO', 'RECHAZADO', 'CANCELADO')", name="estado_valido"
        ),
        CheckConstraint("sistema IN ('FRANCES', 'ALEMAN')", name="sistema"),
        CheckConstraint("capital > 0", name="capital"),
        CheckConstraint("cuotas > 0", name="cuotas"),
        CheckConstraint("ingreso_neto > 0", name="ingreso"),
        CheckConstraint(
            "garante_escribano_id IS DISTINCT FROM escribano_id", name="garante_propio"
        ),
        CheckConstraint(
            "resuelto_por_user_id IS NULL OR resuelto_por_user_id <> creado_por_user_id",
            name="cuatro_ojos",
        ),
        CheckConstraint(
            "(estado = 'RECHAZADO') = (motivo_rechazo IS NOT NULL)", name="rechazo_fundado"
        ),
        CheckConstraint(
            "(estado IN ('OTORGADO', 'CANCELADO')) = (fecha_otorgamiento IS NOT NULL)",
            name="otorgamiento_coherente",
        ),
        CheckConstraint("afectacion <= afectacion_maxima", name="dentro_del_tope"),
        CheckConstraint(MONEDA_VALIDA, name="moneda"),
        Index("ix_prestamos_escribano_estado", "escribano_id", "estado"),
    )

    numero: Mapped[int] = mapped_column(
        Integer,
        server_default=text("nextval('prestamos_numero_seq')"),
        unique=True,
        nullable=False,
    )
    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_escribanos.id", ondelete="RESTRICT"), nullable=False
    )
    linea_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prestamos_lineas.id", ondelete="RESTRICT"), nullable=False
    )
    garante_escribano_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="SOLICITADO", index=True
    )

    # Condiciones congeladas al solicitar (SNAP de la línea).
    sistema: Mapped[str] = mapped_column(String(10), nullable=False)
    tna: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cuotas: Mapped[int] = mapped_column(Integer, nullable=False)
    tasa_es_ejemplo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Copiada de la línea al solicitar; no cambia nunca (trigger). Capital, cuotas, ingreso neto
    # y otras cuotas están en esta moneda.
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, server_default="ARS")

    # Evaluación crediticia.
    ingreso_neto: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Cuotas de otros préstamos vigentes del escribano al evaluar.
    otras_cuotas: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cuota_maxima: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    afectacion: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    afectacion_maxima: Mapped[Decimal] = mapped_column(RATE, nullable=False)

    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_otorgamiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    creado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    resuelto_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CuotaPrestamo(UUIDMixin, Base):
    __tablename__ = "prestamos_cuotas"
    __table_args__ = (
        UniqueConstraint("prestamo_id", "numero", name="uq_prestamos_cuotas_numero"),
        CheckConstraint("numero > 0", name="numero"),
        CheckConstraint("cuota = amortizacion + interes", name="cuota_cuadra"),
        CheckConstraint("saldo_final = saldo_inicial - amortizacion", name="saldo_cuadra"),
        CheckConstraint("amortizacion > 0 AND interes >= 0 AND saldo_final >= 0", name="valores"),
        CheckConstraint("estado IN ('PENDIENTE', 'PAGADA')", name="estado_valido"),
        CheckConstraint(
            "(estado = 'PAGADA') = (fecha_pago IS NOT NULL AND importe_pagado IS NOT NULL "
            "AND registrado_por_user_id IS NOT NULL)",
            name="pago_coherente",
        ),
        Index("ix_prestamos_cuotas_vencimiento_estado", "vencimiento", "estado"),
    )

    prestamo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prestamos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    saldo_inicial: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amortizacion: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    interes: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cuota: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    saldo_final: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDIENTE")
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    importe_pagado: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    registrado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class DocumentoPrestamo(UUIDMixin, Base):
    """Documentación de una solicitud (regla MIME: el archivo se valida y guarda como un
    comprobante). Solo se agrega mientras la solicitud está abierta; no se borra: uno cargado
    por error se anula con motivo y deja de contar (trigger)."""

    __tablename__ = "prestamos_documentos"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('DOCUMENTO_IDENTIDAD', 'CERTIFICADO_INGRESOS', 'CERTIFICADO_BIENES', "
            "'GARANTIA', 'OTRO')",
            name="tipo_valido",
        ),
        CheckConstraint("tipo <> 'OTRO' OR descripcion IS NOT NULL", name="otro_descripto"),
        CheckConstraint("mime_type IN ('application/pdf', 'image/png', 'image/jpeg')", name="mime"),
        CheckConstraint("tamano_bytes > 0", name="tamano"),
        CheckConstraint(
            "(anulado_en IS NULL) = (anulado_por_user_id IS NULL) "
            "AND (anulado_en IS NULL) = (motivo_anulacion IS NULL)",
            name="anulacion_completa",
        ),
        Index("ix_prestamos_documentos_prestamo_tipo", "prestamo_id", "tipo"),
    )

    prestamo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prestamos.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    # Ruta relativa a UPLOAD_DIR; nunca se envía al cliente.
    archivo: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    subido_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anulado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    motivo_anulacion: Mapped[str | None] = mapped_column(Text, nullable=True)
