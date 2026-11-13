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


class VademecumActo(UUIDMixin, Base):
    """Acto del vademécum de aportes de la Caja: cómo aporta cada naturaleza de acto.

    Versionado como los parámetros, con aprobación de otra persona: una fila nunca cambia
    (trigger) salvo su aprobación o rechazo y el cierre de su vigencia; un cambio es una versión
    nueva del mismo código. Cada acto declarado guarda la fila con que se valorizó (SNAP). Los
    montos no están acá: salen del motor paramétrico según la categoría.
    """

    __tablename__ = "ddjj_vademecum"
    __table_args__ = (
        CheckConstraint("codigo ~ '^[A-Z][A-Z0-9_]{2,59}$'", name="codigo_formato"),
        CheckConstraint(
            "categoria IN ('ESCRITURA_CON_VALOR', 'ACTA_O_PODER', 'OTRO_ACTO', 'EXENTO')",
            name="categoria_valida",
        ),
        CheckConstraint(
            "(categoria = 'EXENTO') = (motivo_exencion IS NOT NULL)", name="exento_con_motivo"
        ),
        CheckConstraint(
            "motivo_exencion IS NULL OR motivo_exencion IN ('CONVENIO_IPV', 'ACTA_SUBSANATORIA', "
            "'REGULACION_DOMINIAL', 'ASOCIACION_INTERMEDIA_IPV')",
            name="motivo_exencion",
        ),
        CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="rango_valido"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(
            "estado IN ('PENDIENTE_APROBACION', 'VIGENTE', 'RECHAZADA')", name="estado_valido"
        ),
        CheckConstraint(
            "(estado = 'VIGENTE') = (aprobado_por_user_id IS NOT NULL)", name="aprobacion"
        ),
        CheckConstraint(
            "aprobado_por_user_id IS NULL OR aprobado_por_user_id <> created_by_user_id",
            name="cuatro_ojos",
        ),
        CheckConstraint("fecha_hasta IS NULL OR estado = 'VIGENTE'", name="cierre_aprobada"),
        Index("uq_ddjj_vademecum_codigo_version", "codigo", "version", unique=True),
        # La exclusión sin solapamiento entre versiones aprobadas vive en la migración.
    )

    codigo: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    categoria: Mapped[str] = mapped_column(String(30), nullable=False)
    motivo_exencion: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Condición o alcance que el escribano tiene que leer antes de elegirlo.
    aclaracion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Otras formas de nombrarlo, para el buscador (separadas por coma).
    sinonimos: Mapped[str | None] = mapped_column(String(500), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolucion: Mapped[str] = mapped_column(String(150), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="PENDIENTE_APROBACION", index=True
    )
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


class Acto(UUIDMixin, TimestampMixin, Base):
    """Renglón de la DDJJ: un acto autorizado por un escribano del registro."""

    __tablename__ = "ddjj_actos"
    __table_args__ = (
        CheckConstraint(
            "categoria IN ('ESCRITURA_CON_VALOR', 'ACTA_O_PODER', 'OTRO_ACTO', 'SIN_EFECTO', "
            "'EXENTO')",
            name="categoria_valida",
        ),
        # Un acto exento siempre dice por qué; «otro motivo», con detalle.
        CheckConstraint(
            "(categoria = 'EXENTO') = (motivo_exencion IS NOT NULL)", name="exento_con_motivo"
        ),
        CheckConstraint(
            "motivo_exencion IS NULL OR motivo_exencion IN ('CONVENIO_IPV', 'ACTA_SUBSANATORIA', "
            "'REGULACION_DOMINIAL', 'ASOCIACION_INTERMEDIA_IPV', 'OTRO')",
            name="motivo_exencion",
        ),
        CheckConstraint(
            "motivo_exencion IS DISTINCT FROM 'OTRO' OR length(detalle_exencion) >= 3",
            name="exencion_otro_con_detalle",
        ),
        CheckConstraint(
            "detalle_exencion IS NULL OR motivo_exencion IS NOT NULL", name="detalle_exencion"
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
        # Precio y avalúo: la base es el mayor de los dos (vademécum: «el mayor valor de precio
        # o avalúo»). Un acto cargado solo con la base no los tiene.
        CheckConstraint(
            "(precio IS NULL AND avaluo IS NULL) OR (categoria = 'ESCRITURA_CON_VALOR' "
            "AND base_imponible = GREATEST(COALESCE(precio, 0), COALESCE(avaluo, 0)))",
            name="base_es_el_mayor",
        ),
        CheckConstraint("precio IS NULL OR precio >= 0", name="precio"),
        CheckConstraint("avaluo IS NULL OR avaluo >= 0", name="avaluo"),
        CheckConstraint(
            "NOT (fuera_de_vademecum AND vademecum_id IS NOT NULL)", name="fuera_de_vademecum"
        ),
        CheckConstraint(
            "aporte_individual IS NULL OR aporte IS NOT NULL", name="aporte_individual"
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
    # Solo para la categoría EXENTO.
    motivo_exencion: Mapped[str | None] = mapped_column(String(30), nullable=True)
    detalle_exencion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Acto del vademécum elegido (SNAP de cómo aporta). NULL: cargado sin vademécum (actos
    # anteriores, «sin efecto») o declarado como no listado (`fuera_de_vademecum`).
    vademecum_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ddjj_vademecum.id", ondelete="RESTRICT"), nullable=True
    )
    # El escribano no lo encontró en el vademécum y eligió la categoría: la Caja lo revisa.
    fuera_de_vademecum: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    precio: Mapped[Decimal | None] = mapped_column(BASE, nullable=True)
    avaluo: Mapped[Decimal | None] = mapped_column(BASE, nullable=True)
    # Escritura con varios actos: ¿intervienen solo las mismas partes? Rige para toda la
    # escritura (todos sus renglones lo tienen igual) y decide el criterio de pluralidad.
    mismas_partes: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
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
    # Lo que aportaría el acto solo; `aporte` es lo que aporta tras el criterio de pluralidad.
    aporte_individual: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    vigencia_pluralidad_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_vigencias.id", ondelete="RESTRICT"),
        nullable=True,
    )

    escribano = relationship("Escribano", lazy="joined", innerjoin=True)
    vademecum = relationship(VademecumActo, lazy="joined")


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
        # Boleta de un escribano (desde las boletas por notario) o del registro (las anteriores):
        # escribano, cargo y modalidad van juntos.
        CheckConstraint(
            "(escribano_id IS NULL) = (cargo IS NULL) "
            "AND (escribano_id IS NULL) = (modalidad IS NULL)",
            name="escribano_completo",
        ),
        CheckConstraint(
            "modalidad IS NULL OR modalidad IN ('COMPLETA', 'CON_MINIMO', 'SOLO_ACTOS')",
            name="modalidad_valida",
        ),
        CheckConstraint(
            "modalidad IS NULL OR modalidad = 'COMPLETA' OR aporte_medico = 0",
            name="medico_solo_completa",
        ),
        CheckConstraint(
            "modalidad IS DISTINCT FROM 'SOLO_ACTOS' OR aporte_minimo = 0",
            name="solo_actos_sin_minimo",
        ),
        # Una sola boleta pendiente por escribano y DDJJ (las del registro cuentan como una).
        Index(
            "uq_ddjj_boletas_pendiente",
            "ddjj_id",
            "escribano_id",
            unique=True,
            postgresql_where=text("estado = 'PENDIENTE'"),
            postgresql_nulls_not_distinct=True,
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
    # De quién es la boleta, con qué cargo y qué cobra (ModalidadBoleta), congelados al emitir.
    # Vacíos en las boletas emitidas antes de las boletas por notario: eran del registro.
    escribano_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("padron_escribanos.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    cargo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    modalidad: Mapped[str | None] = mapped_column(String(20), nullable=True)

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

    # Detalle del interés por tasa vigente (SNAP); vacío si se paga en término.
    tramos_mora: Mapped[list["BoletaTramoMora"]] = relationship(
        lazy="selectin", order_by="BoletaTramoMora.orden"
    )


class BoletaTramoMora(UUIDMixin, Base):
    """Días de atraso de una boleta en que rigió una misma tasa de mora, con su interés.

    Se escribe al emitir la boleta y no se modifica ni se borra (regla INM).
    """

    __tablename__ = "ddjj_boletas_tramos_mora"
    __table_args__ = (
        CheckConstraint("orden > 0", name="orden"),
        CheckConstraint("hasta >= desde", name="fechas"),
        CheckConstraint("dias = hasta - desde + 1", name="dias"),
        CheckConstraint("tasa >= 0", name="tasa"),
        CheckConstraint("periodo_tasa IN ('MENSUAL', 'ANUAL')", name="periodo_tasa"),
        CheckConstraint("interes >= 0", name="interes"),
        Index("uq_ddjj_boletas_tramos_mora_orden", "boleta_id", "orden", unique=True),
    )

    boleta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ddjj_boletas.id", ondelete="RESTRICT"), nullable=False
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    dias: Mapped[int] = mapped_column(Integer, nullable=False)
    vigencia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parametros_vigencias.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Copia de la tasa aplicada: se lee sin ir a la vigencia y queda en la huella.
    tasa: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    periodo_tasa: Mapped[str] = mapped_column(String(10), nullable=False)
    interes: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
