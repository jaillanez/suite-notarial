"""Autoridades, novedades y documentos oficiales del sitio institucional (Módulo 8).

- Nada se borra (INM): autoridades con baja lógica; novedades y documentos se archivan.
- Un documento tiene una URL canónica estable (`slug`); cada archivo que se sube es una versión
  nueva e inmutable (trigger). El sitio sirve siempre la última versión y conserva el histórico.
- La huella SHA-256 de cada versión se verifica al servirla: un PDF alterado no se entrega.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

SLUG_CHECK = "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'"
ESTADOS_CHECK = "estado IN ('BORRADOR', 'PUBLICADO', 'ARCHIVADO')"


class Autoridad(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "cms_autoridades"
    __table_args__ = (CheckConstraint("orden >= 0", name="orden"),)

    cargo: Mapped[str] = mapped_column(String(100), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mandato_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    mandato_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class Novedad(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "cms_novedades"
    __table_args__ = (
        CheckConstraint(SLUG_CHECK, name="slug_formato"),
        CheckConstraint(ESTADOS_CHECK, name="estado_valido"),
        CheckConstraint(
            "estado = 'BORRADOR' OR fecha_publicacion IS NOT NULL", name="publicada_con_fecha"
        ),
    )

    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    resumen: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # Texto plano en párrafos (sin HTML): se muestra escapado, no hay inyección posible.
    contenido: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="BORRADOR", index=True
    )
    fecha_publicacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    autor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )


class Documento(UUIDMixin, TimestampMixin, Base):
    """Documento oficial con URL canónica: `/sitio/documentos/{slug}.pdf`."""

    __tablename__ = "cms_documentos"
    __table_args__ = (
        CheckConstraint(SLUG_CHECK, name="slug_formato"),
        CheckConstraint(ESTADOS_CHECK, name="estado_valido"),
        CheckConstraint(
            "tipo IN ('ESTADO_CONTABLE', 'MEMORIA_ANUAL', 'RESOLUCION', 'OTRO')", name="tipo"
        ),
        CheckConstraint("ejercicio BETWEEN 1950 AND 2200", name="ejercicio"),
        CheckConstraint(
            "(fecha_publicacion IS NULL) = (primera_version_publica IS NULL)",
            name="publicacion_coherente",
        ),
    )

    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    ejercicio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="BORRADOR", index=True
    )
    fecha_publicacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Versión vigente al publicarse por primera vez: las anteriores (borradores) nunca fueron
    # públicas y no se exponen en el sitio.
    primera_version_publica: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )


class DocumentoVersion(UUIDMixin, Base):
    """Archivo de un documento. Inmutable: reemplazar es subir una versión nueva."""

    __tablename__ = "cms_documento_versiones"
    __table_args__ = (
        UniqueConstraint("documento_id", "version", name="uq_cms_documento_versiones_version"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("paginas > 0", name="paginas"),
        CheckConstraint("tamano_bytes > 0", name="tamano"),
    )

    documento_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cms_documentos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    archivo: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paginas: Mapped[int] = mapped_column(Integer, nullable=False)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    subido_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
