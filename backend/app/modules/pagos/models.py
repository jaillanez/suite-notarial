"""Comprobantes de pago y asientos de conciliación (Módulo 6).

- El escribano adjunta un comprobante a una boleta pendiente: queda PENDIENTE_REVISION.
- Tesorería lo aprueba o lo rechaza; cada decisión deja un asiento inmutable en
  `pagos_conciliaciones`. Recién con un asiento aprobado la boleta puede pasar a PAGADA (trigger).
- El archivo se guarda fuera del webroot con nombre UUID; acá quedan su tipo real, tamaño y huella.
- Un pago con Mercado Pago aprobado genera un comprobante de origen MERCADO_PAGO (sin archivo):
  también queda en revisión hasta que Tesorería lo confirma. Lo mismo un pago con el botón de
  pagos Supervielle (origen SUPERVIELLE).
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
    Integer,
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
            "origen IN ('ARCHIVO', 'MERCADO_PAGO', 'SUPERVIELLE')", name="origen_valido"
        ),
        # El archivo es obligatorio solo para el comprobante que adjunta el escribano.
        CheckConstraint(
            "(origen = 'ARCHIVO') = (archivo IS NOT NULL AND nombre_original IS NOT NULL "
            "AND mime_type IS NOT NULL AND tamano_bytes IS NOT NULL AND sha256 IS NOT NULL)",
            name="archivo_segun_origen",
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

    origen: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ARCHIVO")
    # Archivo (regla MIME): tipo real por magic bytes, nombre UUID, huella para detectar cambios.
    # Vacíos en un comprobante de Mercado Pago.
    nombre_original: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archivo: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tamano_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

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


class PagoMercadoPago(UUIDMixin, Base):
    """Registro de cada cobro armado con Mercado Pago y del pago que informa (no se borra).

    El cobro es de una boleta o de una cuota de préstamo, nunca de las dos. El `id` viaja como
    `external_reference`: así cada pago de Mercado Pago se vincula a lo que paga y a quien lo
    inició. Los importes y estados se toman siempre de la API de Mercado Pago, nunca de lo que
    informa el navegador.

    Una cuota no tiene comprobante en la mesa de Tesorería: el pago aprobado queda a confirmar y
    Tesorería lo confirma desde el préstamo (`confirmado_por_user_id`, `confirmado_en`). Recién
    ahí la cuota pasa a pagada (regla PAGO).
    """

    __tablename__ = "pagos_mercadopago"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('CREADO', 'pending', 'authorized', 'in_process', 'in_mediation', "
            "'approved', 'rejected', 'cancelled', 'refunded', 'charged_back')",
            name="estado_valido",
        ),
        CheckConstraint("importe_boleta > 0", name="importe_boleta"),
        CheckConstraint("estado = 'CREADO' OR mp_payment_id IS NOT NULL", name="pago_informado"),
        CheckConstraint("(boleta_id IS NULL) <> (cuota_id IS NULL)", name="boleta_o_cuota"),
        CheckConstraint(
            "(confirmado_en IS NULL) = (confirmado_por_user_id IS NULL)",
            name="confirmacion_completa",
        ),
        # Se confirma solo un pago aprobado (lo controla el servicio); después Mercado Pago
        # puede informar una devolución o un contracargo, y ese estado tiene que poder guardarse.
        CheckConstraint(
            "confirmado_en IS NULL OR cuota_id IS NOT NULL",
            name="confirma_solo_cuota",
        ),
        # Una cuota se cobra una sola vez.
        Index(
            "uq_pagos_mercadopago_cuota_confirmada",
            "cuota_id",
            unique=True,
            postgresql_where=text("confirmado_en IS NOT NULL"),
        ),
    )

    boleta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_boletas.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    cuota_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prestamos_cuotas.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    preference_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # Lo que se le pidió a Mercado Pago: el total de la boleta o el importe de la cuota.
    importe_boleta: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    iniciado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="CREADO")
    # Lo que informa Mercado Pago del pago.
    mp_payment_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    estado_detalle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    medio_pago: Mapped[str | None] = mapped_column(String(50), nullable=True)
    moneda: Mapped[str | None] = mapped_column(String(3), nullable=True)
    importe_pagado: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    comision: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    importe_neto: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Comprobante que quedó en la mesa de Tesorería (al aprobarse el pago).
    comprobante_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pagos_comprobantes.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    # Tesorería confirmó el cobro de la cuota (solo en el cobro de una cuota).
    confirmado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Numera las publicaciones: el banco pide un `id_publicacion` numérico que no se repita.
SECUENCIA_PUBLICACION_SPV = "pagos_supervielle_publicacion_seq"


class PagoSupervielle(UUIDMixin, Base):
    """Cada deuda publicada en el botón de pagos Supervielle y el pago que informa (no se borra).

    La deuda es de una boleta o de una cuota de préstamo en pesos, nunca de las dos. Se publica
    cuando el escribano pide pagar, por el importe exacto (la comisión la absorbe la Caja): el
    total de la boleta con vencimiento en su fecha de pago, o la cuota del plan. El banco no
    permite anularla (TODO(banco): confirmar), así que mientras siga vigente se reutiliza su
    link en lugar de publicar otra. El `id` viaja en
    `identificadores` y el banco identifica la deuda con `hash`. El estado y el importe del pago
    se toman siempre de la API del banco.

    Una cuota no tiene comprobante en la mesa de Tesorería (la mesa es de boletas): el pago hecho
    queda a confirmar y Tesorería lo confirma desde el préstamo (`confirmado_por_user_id`,
    `confirmado_en`), como con Mercado Pago. Recién ahí la cuota pasa a pagada (regla PAGO).
    """

    __tablename__ = "pagos_supervielle"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('CREADO', 'APROBADO', 'ACREDITADO', 'PENDIENTE', 'REVERSADO', 'ANULADO')",
            name="estado_valido",
        ),
        CheckConstraint("importe_boleta > 0", name="importe_boleta"),
        CheckConstraint("estado = 'CREADO' OR spv_pago_id IS NOT NULL", name="pago_informado"),
        CheckConstraint("(boleta_id IS NULL) <> (cuota_id IS NULL)", name="boleta_o_cuota"),
        CheckConstraint(
            "(confirmado_en IS NULL) = (confirmado_por_user_id IS NULL)",
            name="confirmacion_completa",
        ),
        # Se confirma solo un pago hecho (lo controla el servicio); después el banco puede
        # informar una reversión, y ese estado tiene que poder guardarse.
        CheckConstraint(
            "confirmado_en IS NULL OR cuota_id IS NOT NULL", name="confirma_solo_cuota"
        ),
        # Una cuota se cobra una sola vez.
        Index(
            "uq_pagos_supervielle_cuota_confirmada",
            "cuota_id",
            unique=True,
            postgresql_where=text("confirmado_en IS NOT NULL"),
        ),
    )

    boleta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ddjj_boletas.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    cuota_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prestamos_cuotas.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    id_publicacion: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    hash: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    link_pago: Mapped[str] = mapped_column(String(500), nullable=False)
    # Lo que se publicó: el total de la boleta (o la cuota) y su vencimiento.
    importe_boleta: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    vence: Mapped[date] = mapped_column(Date, nullable=False)
    iniciado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="CREADO")
    # Lo que informa el banco del pago.
    spv_pago_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    medio_pago: Mapped[str | None] = mapped_column(String(50), nullable=True)
    importe_pagado: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    pagado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Comisión estimada, IVA incluido, con los parámetros vigentes a la fecha del pago (la API no
    # la informa) y las vigencias con que se estimó (regla SNAP). Vacía si faltaba algún parámetro.
    comision_estimada: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    vigencia_comision_boton_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parametros_vigencias.id"), nullable=True
    )
    vigencia_comision_medio_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parametros_vigencias.id"), nullable=True
    )
    vigencia_comision_iva_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parametros_vigencias.id"), nullable=True
    )
    # Última consulta al banco disparada por un aviso, y hora del aviso más viejo todavía sin
    # consultar (lo procesa el cron): la pausa entre avisos vive en la base.
    consultado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aviso_pendiente_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Avisos recibidos sin consultar: sube con cada uno. La marca se borra solo si no cambió
    # mientras se consultaba (un aviso que llega en el medio la conserva).
    aviso_generacion: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Cuándo se alertó a Tesorería de un aviso demorado (una alerta por marca).
    aviso_alertado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Comprobante que quedó en la mesa de Tesorería (al aprobarse el pago).
    comprobante_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pagos_comprobantes.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    # Tesorería confirmó el cobro de la cuota (solo en la deuda de una cuota).
    confirmado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
