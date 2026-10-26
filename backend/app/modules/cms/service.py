"""Sitio institucional: autoridades, novedades y documentos oficiales (Módulo 8).

Toda alta, edición o cambio de estado se audita. Un documento nunca cambia de archivo: cada
reemplazo es una versión nueva e inmutable, y la URL canónica sirve siempre la última, con su
huella verificada.
"""

import re
import unicodedata
import uuid
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.pagination import PageParams
from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.cms.catalog import TRANSICIONES, EstadoPublicacion
from app.modules.cms.models import Autoridad, Documento, DocumentoVersion, Novedad
from app.modules.cms.schemas import (
    AutoridadIn,
    AutoridadUpdate,
    DocumentoIn,
    DocumentoUpdate,
    NovedadIn,
)
from app.modules.iam.models import User
from app.modules.pagos import storage

SUBDIR = "documentos-oficiales"
PUBLICADO = EstadoPublicacion.PUBLICADO.value


def _not_found(what: str) -> ProblemError:
    return ProblemError(HTTPStatus.NOT_FOUND, f"{what} no existe.")


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def slugify(texto: str) -> str:
    """ "Estados contables 2025" -> "estados-contables-2025" (sin tildes ni símbolos)."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")
    return slug[:140] or "documento"


async def _slug_libre(
    session: AsyncSession, model: type[Novedad] | type[Documento], base: str
) -> str:
    slug, n = base, 1
    while await session.scalar(select(model.id).where(model.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


def _valores(obj: object, campos: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in campos:
        v = getattr(obj, c)
        out[c] = v.isoformat() if isinstance(v, date | datetime) else v
    return out


def _transicion(actual: str, nuevo: EstadoPublicacion) -> None:
    if nuevo not in TRANSICIONES[EstadoPublicacion(actual)]:
        raise _conflict(f"No se puede pasar de {actual.lower()} a {nuevo.value.lower()}.")


# --------------------------------------------------------------------------- autoridades

AUTORIDAD_CAMPOS = ("cargo", "nombre", "orden", "mandato_desde", "mandato_hasta", "is_active")


async def list_autoridades(session: AsyncSession, *, solo_activas: bool) -> list[Autoridad]:
    stmt = select(Autoridad).order_by(Autoridad.orden, Autoridad.cargo, Autoridad.nombre)
    if solo_activas:
        stmt = stmt.where(Autoridad.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def crear_autoridad(
    session: AsyncSession, ctx: RequestContext, actor: User, data: AutoridadIn
) -> Autoridad:
    item = Autoridad(id=uuid.uuid4(), **data.model_dump(), created_by_user_id=actor.id)
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_AUTORIDAD_CREADA,
        actor_user_id=actor.id,
        new_value=_valores(item, AUTORIDAD_CAMPOS[:-1]),
        details={"autoridad_id": str(item.id)},
    )
    await session.commit()
    await session.refresh(item)
    return item


async def actualizar_autoridad(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    autoridad_id: uuid.UUID,
    data: AutoridadUpdate,
) -> Autoridad:
    item = await session.get(Autoridad, autoridad_id, with_for_update=True)
    if item is None:
        raise _not_found("La autoridad")
    antes = _valores(item, AUTORIDAD_CAMPOS)
    for campo, valor in data.model_dump().items():
        setattr(item, campo, valor)
    despues = _valores(item, AUTORIDAD_CAMPOS)
    cambios = [c for c in AUTORIDAD_CAMPOS if antes[c] != despues[c]]
    if cambios:
        record_audit(
            session,
            ctx,
            AuditEvent.CMS_AUTORIDAD_ACTUALIZADA,
            actor_user_id=actor.id,
            old_value={c: antes[c] for c in cambios},
            new_value={c: despues[c] for c in cambios},
            details={"autoridad_id": str(item.id)},
        )
    await session.commit()
    # `updated_at` lo calcula la base: se relee antes de serializar.
    await session.refresh(item)
    return item


# --------------------------------------------------------------------------- novedades

NOVEDAD_CAMPOS = ("slug", "titulo", "resumen", "contenido")


async def list_novedades(
    session: AsyncSession, estado: EstadoPublicacion | None, page: PageParams
) -> tuple[list[Novedad], int]:
    stmt = select(Novedad)
    if estado is not None:
        stmt = stmt.where(Novedad.estado == estado.value)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.scalars(
        stmt.order_by(
            Novedad.fecha_publicacion.desc().nulls_first(), Novedad.created_at.desc(), Novedad.id
        )
        .offset(page.offset)
        .limit(page.page_size)
    )
    return list(result.all()), total or 0


async def get_novedad(
    session: AsyncSession, novedad_id: uuid.UUID, *, lock: bool = False
) -> Novedad:
    item = await session.get(Novedad, novedad_id, with_for_update=lock)
    if item is None:
        raise _not_found("La novedad")
    return item


async def crear_novedad(
    session: AsyncSession, ctx: RequestContext, actor: User, data: NovedadIn
) -> Novedad:
    slug = data.slug or await _slug_libre(session, Novedad, slugify(data.titulo))
    item = Novedad(
        id=uuid.uuid4(),
        slug=slug,
        titulo=data.titulo,
        resumen=data.resumen,
        contenido=data.contenido,
        estado=EstadoPublicacion.BORRADOR.value,
        autor_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_NOVEDAD_CREADA,
        actor_user_id=actor.id,
        new_value=_valores(item, NOVEDAD_CAMPOS),
        details={"novedad_id": str(item.id)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Ya hay una novedad con ese enlace.") from exc
    await session.refresh(item)
    return item


async def actualizar_novedad(
    session: AsyncSession, ctx: RequestContext, actor: User, novedad_id: uuid.UUID, data: NovedadIn
) -> Novedad:
    item = await get_novedad(session, novedad_id, lock=True)
    antes = _valores(item, NOVEDAD_CAMPOS)
    if data.slug and data.slug != item.slug:
        if item.estado != EstadoPublicacion.BORRADOR.value:
            raise _conflict("El enlace de una novedad publicada no cambia.")
        item.slug = data.slug
    item.titulo = data.titulo
    item.resumen = data.resumen
    item.contenido = data.contenido
    despues = _valores(item, NOVEDAD_CAMPOS)
    cambios = [c for c in NOVEDAD_CAMPOS if antes[c] != despues[c]]
    if cambios:
        record_audit(
            session,
            ctx,
            AuditEvent.CMS_NOVEDAD_ACTUALIZADA,
            actor_user_id=actor.id,
            old_value={c: antes[c] for c in cambios},
            new_value={c: despues[c] for c in cambios},
            details={"novedad_id": str(item.id), "estado": item.estado},
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Ya hay una novedad con ese enlace.") from exc
    # `updated_at` lo calcula la base: se relee antes de serializar.
    await session.refresh(item)
    return item


async def estado_novedad(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    novedad_id: uuid.UUID,
    nuevo: EstadoPublicacion,
) -> Novedad:
    item = await get_novedad(session, novedad_id, lock=True)
    anterior = item.estado
    _transicion(anterior, nuevo)
    item.estado = nuevo.value
    if nuevo is EstadoPublicacion.PUBLICADO and item.fecha_publicacion is None:
        item.fecha_publicacion = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_NOVEDAD_ESTADO,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": anterior},
        new_value={"estado": nuevo.value},
        details={"novedad_id": str(item.id), "slug": item.slug},
    )
    await session.commit()
    # `updated_at` lo calcula la base: se relee antes de serializar.
    await session.refresh(item)
    return item


async def novedades_publicadas(
    session: AsyncSession, page: PageParams
) -> tuple[list[Novedad], int]:
    return await list_novedades(session, EstadoPublicacion.PUBLICADO, page)


async def novedad_publicada(session: AsyncSession, slug: str) -> Novedad:
    item = await session.scalar(
        select(Novedad).where(Novedad.slug == slug, Novedad.estado == PUBLICADO)
    )
    if item is None:
        raise _not_found("La novedad")
    return item


# --------------------------------------------------------------------------- documentos


async def list_documentos(session: AsyncSession, *, solo_publicados: bool) -> list[Documento]:
    stmt = select(Documento).order_by(
        Documento.tipo, Documento.ejercicio.desc(), Documento.titulo, Documento.id
    )
    if solo_publicados:
        stmt = stmt.where(Documento.estado == PUBLICADO)
    return list((await session.scalars(stmt)).all())


async def get_documento(
    session: AsyncSession, documento_id: uuid.UUID, *, lock: bool = False
) -> Documento:
    item = await session.get(Documento, documento_id, with_for_update=lock)
    if item is None:
        raise _not_found("El documento")
    return item


async def versiones(session: AsyncSession, documento_id: uuid.UUID) -> list[DocumentoVersion]:
    result = await session.scalars(
        select(DocumentoVersion)
        .where(DocumentoVersion.documento_id == documento_id)
        .order_by(DocumentoVersion.version.desc())
    )
    return list(result.all())


async def versiones_publicas(session: AsyncSession, documento: Documento) -> list[DocumentoVersion]:
    """Versiones que el público puede ver: desde la vigente al publicarse por primera vez.

    Los reemplazos hechos mientras el documento era borrador nunca fueron públicos.
    """
    if documento.primera_version_publica is None:
        return []
    todas = await versiones(session, documento.id)
    return [v for v in todas if v.version >= documento.primera_version_publica]


async def _agregar_version(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    documento: Documento,
    archivo: storage.ArchivoValidado,
    paginas: int,
    motivo: str | None,
) -> tuple[DocumentoVersion, str]:
    numero = (
        await session.scalar(
            select(func.coalesce(func.max(DocumentoVersion.version), 0)).where(
                DocumentoVersion.documento_id == documento.id
            )
        )
        or 0
    ) + 1
    relativa = await storage.guardar(settings, archivo, today_local(), subdir=SUBDIR)
    version = DocumentoVersion(
        id=uuid.uuid4(),
        documento_id=documento.id,
        version=numero,
        nombre_original=archivo.nombre_original,
        archivo=relativa,
        sha256=archivo.sha256,
        tamano_bytes=archivo.tamano,
        paginas=paginas,
        motivo=motivo,
        subido_por_user_id=actor.id,
    )
    session.add(version)
    return version, relativa


async def _commit_con_archivo(session: AsyncSession, settings: Settings, relativa: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        await storage.eliminar(settings, relativa)
        raise _conflict("Ya hay un documento con ese enlace.") from exc
    except BaseException:
        await storage.eliminar(settings, relativa)
        raise


async def crear_documento(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    actor: User,
    data: DocumentoIn,
    archivo: storage.ArchivoValidado,
    paginas: int,
) -> Documento:
    slug = data.slug or await _slug_libre(
        session, Documento, slugify(f"{data.titulo} {data.ejercicio}")
    )
    if await session.scalar(select(Documento.id).where(Documento.slug == slug)):
        raise _conflict("Ya hay un documento con ese enlace.")
    item = Documento(
        id=uuid.uuid4(),
        slug=slug,
        tipo=data.tipo.value,
        ejercicio=data.ejercicio,
        titulo=data.titulo,
        descripcion=data.descripcion,
        estado=EstadoPublicacion.BORRADOR.value,
        created_by_user_id=actor.id,
    )
    session.add(item)
    await session.flush()
    version, relativa = await _agregar_version(
        session, settings, actor, item, archivo, paginas, None
    )
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_DOCUMENTO_CREADO,
        actor_user_id=actor.id,
        new_value={
            "slug": slug,
            "tipo": data.tipo.value,
            "ejercicio": data.ejercicio,
            "titulo": data.titulo,
            "sha256": version.sha256,
            "paginas": paginas,
        },
        details={"documento_id": str(item.id)},
    )
    await _commit_con_archivo(session, settings, relativa)
    return item


async def nueva_version(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    actor: User,
    documento_id: uuid.UUID,
    archivo: storage.ArchivoValidado,
    paginas: int,
    motivo: str,
) -> Documento:
    """Reemplaza el archivo sin romper el enlace: la versión anterior queda en el histórico."""
    item = await get_documento(session, documento_id, lock=True)
    anterior = (await versiones(session, item.id))[0]
    if anterior.sha256 == archivo.sha256:
        raise _conflict("El archivo es idéntico a la versión vigente.")
    version, relativa = await _agregar_version(
        session, settings, actor, item, archivo, paginas, motivo
    )
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_DOCUMENTO_VERSION,
        severity=Severity.WARNING if item.estado == PUBLICADO else Severity.INFO,
        actor_user_id=actor.id,
        old_value={"version": anterior.version, "sha256": anterior.sha256},
        new_value={"version": version.version, "sha256": version.sha256, "paginas": paginas},
        details={"documento_id": str(item.id), "slug": item.slug, "motivo": motivo},
    )
    item.updated_at = datetime.now(UTC)
    await _commit_con_archivo(session, settings, relativa)
    # `updated_at` lo calcula la base: se relee antes de serializar.
    await session.refresh(item)
    return item


async def actualizar_documento(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    documento_id: uuid.UUID,
    data: DocumentoUpdate,
) -> Documento:
    item = await get_documento(session, documento_id, lock=True)
    antes = _valores(item, ("titulo", "descripcion"))
    item.titulo = data.titulo
    item.descripcion = data.descripcion
    despues = _valores(item, ("titulo", "descripcion"))
    if antes != despues:
        record_audit(
            session,
            ctx,
            AuditEvent.CMS_DOCUMENTO_ACTUALIZADO,
            actor_user_id=actor.id,
            old_value=antes,
            new_value=despues,
            details={"documento_id": str(item.id), "slug": item.slug},
        )
    await session.commit()
    # `updated_at` lo calcula la base: se relee antes de serializar.
    await session.refresh(item)
    return item


async def estado_documento(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    documento_id: uuid.UUID,
    nuevo: EstadoPublicacion,
) -> Documento:
    item = await get_documento(session, documento_id, lock=True)
    anterior = item.estado
    _transicion(anterior, nuevo)
    vigente = (await versiones(session, item.id))[0].version
    item.estado = nuevo.value
    if nuevo is EstadoPublicacion.PUBLICADO and item.fecha_publicacion is None:
        item.fecha_publicacion = datetime.now(UTC)
        item.primera_version_publica = vigente
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_DOCUMENTO_ESTADO,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": anterior},
        new_value={"estado": nuevo.value},
        details={"documento_id": str(item.id), "slug": item.slug},
    )
    await session.commit()
    # `updated_at` lo calcula la base: se relee antes de serializar.
    await session.refresh(item)
    return item


async def documento_publicado(session: AsyncSession, slug: str) -> Documento:
    item = await session.scalar(
        select(Documento).where(Documento.slug == slug, Documento.estado == PUBLICADO)
    )
    if item is None:
        raise _not_found("El documento")
    return item


async def verificar(settings: Settings, version: DocumentoVersion) -> bool:
    try:
        await storage.leer(settings, version.archivo, version.sha256)
    except (storage.ArchivoAlteradoError, FileNotFoundError):
        return False
    return True


async def contenido_verificado(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    documento: Documento,
    version: DocumentoVersion,
) -> bytes:
    """Bytes del PDF solo si coinciden con la huella registrada; si no, se audita y no se sirve."""
    try:
        return await storage.leer(settings, version.archivo, version.sha256)
    except (storage.ArchivoAlteradoError, FileNotFoundError) as exc:
        record_audit(
            session,
            ctx,
            AuditEvent.CMS_DOCUMENTO_ALTERADO,
            severity=Severity.CRITICAL,
            details={
                "documento_id": str(documento.id),
                "slug": documento.slug,
                "version": version.version,
                "error": type(exc).__name__,
            },
        )
        await session.commit()
        raise ProblemError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "El documento no está disponible en este momento: su archivo no superó el control "
            "de integridad. La Caja ya fue notificada.",
            type_="urn:suite-notarial:cms:documento-alterado",
        ) from exc
