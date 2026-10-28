"""Sitio institucional como diario: imagen de las notas, páginas del menú y armado de portada.

- La imagen de una nota se valida por magic bytes (JPG, PNG o WEBP, hasta 5 MB), se guarda con
  nombre UUID fuera del webroot y con su huella: al servirla se verifica que no cambió.
- Las páginas institucionales (Quiénes somos, Ley de creación…) siguen el mismo ciclo editorial
  que las novedades y nunca se borran.
- La portada se guarda como versión nueva cada vez (nunca se modifica una anterior); la vigente
  es la última. El sitio público solo muestra notas publicadas: una nota archivada desaparece de
  la portada sin que haya que rearmarla.
"""

import hashlib
import uuid
from http import HTTPStatus
from typing import Any

import magic
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.cms.catalog import (
    ANCHOS,
    MAX_IMAGEN_MB,
    MIME_IMAGEN,
    EstadoPublicacion,
)
from app.modules.cms.models import Novedad, Pagina, PortadaVersion
from app.modules.cms.schemas import PaginaIn, PortadaIn
from app.modules.cms.service import (
    PUBLICADO,
    _conflict,
    _not_found,
    _slug_libre,
    _transicion,
    _valores,
    get_novedad,
    slugify,
)
from app.modules.iam.models import User
from app.modules.pagos import storage
from app.modules.pagos.storage import ArchivoInvalidoError, ArchivoValidado

SUBDIR_IMAGENES = "sitio-imagenes"

# --------------------------------------------------------------------------- imagen de la nota


async def validar_imagen(file: UploadFile) -> ArchivoValidado:
    max_bytes = MAX_IMAGEN_MB * 1024 * 1024
    partes: list[bytes] = []
    total = 0
    while chunk := await file.read(storage.CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ArchivoInvalidoError(
                f"La imagen supera el máximo de {MAX_IMAGEN_MB} MB.", status=413
            )
        partes.append(chunk)
    contenido = b"".join(partes)
    if not contenido:
        raise ArchivoInvalidoError("La imagen está vacía.", status=422)
    mime_type = magic.from_buffer(contenido[:2048], mime=True)
    if mime_type not in MIME_IMAGEN:
        raise ArchivoInvalidoError(
            "Formato no admitido: la imagen tiene que ser JPG, PNG o WEBP.", status=415
        )
    return ArchivoValidado(
        contenido=contenido,
        mime_type=mime_type,
        extension=MIME_IMAGEN[mime_type],
        sha256=hashlib.sha256(contenido).hexdigest(),
        nombre_original=storage.nombre_original_seguro(file.filename),
    )


async def poner_imagen(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    actor: User,
    novedad_id: uuid.UUID,
    archivo: ArchivoValidado,
    alt: str,
) -> Novedad:
    item = await get_novedad(session, novedad_id, lock=True)
    anterior = item.imagen_sha256
    relativa = await storage.guardar(settings, archivo, today_local(), subdir=SUBDIR_IMAGENES)
    item.imagen_ruta = relativa
    item.imagen_mime = archivo.mime_type
    item.imagen_sha256 = archivo.sha256
    item.imagen_alt = alt
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_NOVEDAD_IMAGEN,
        actor_user_id=actor.id,
        old_value={"imagen_sha256": anterior},
        new_value={"imagen_sha256": archivo.sha256, "imagen_alt": alt},
        details={"novedad_id": str(item.id), "tamano_bytes": archivo.tamano},
    )
    try:
        await session.commit()
    except BaseException:
        # El registro no llegó a la base: no queda un archivo huérfano.
        await storage.eliminar(settings, relativa)
        raise
    await session.refresh(item)
    return item


async def quitar_imagen(
    session: AsyncSession, ctx: RequestContext, actor: User, novedad_id: uuid.UUID
) -> Novedad:
    """Desvincula la imagen; el archivo se conserva (la auditoría guarda su huella)."""
    item = await get_novedad(session, novedad_id, lock=True)
    if item.imagen_ruta is None:
        return item
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_NOVEDAD_IMAGEN,
        actor_user_id=actor.id,
        old_value={"imagen_sha256": item.imagen_sha256},
        new_value={"imagen_sha256": None},
        details={"novedad_id": str(item.id)},
    )
    item.imagen_ruta = item.imagen_mime = item.imagen_sha256 = item.imagen_alt = None
    await session.commit()
    await session.refresh(item)
    return item


async def contenido_imagen(settings: Settings, item: Novedad) -> bytes:
    if item.imagen_ruta is None or item.imagen_sha256 is None:
        raise _not_found("La imagen")
    try:
        return await storage.leer(settings, item.imagen_ruta, item.imagen_sha256)
    except (storage.ArchivoAlteradoError, FileNotFoundError) as exc:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La imagen no está disponible.") from exc


# --------------------------------------------------------------------------- páginas

PAGINA_CAMPOS = ("slug", "grupo", "titulo", "contenido", "orden")


async def list_paginas(session: AsyncSession, *, solo_publicadas: bool) -> list[Pagina]:
    stmt = select(Pagina)
    if solo_publicadas:
        stmt = stmt.where(Pagina.estado == PUBLICADO)
    result = await session.scalars(stmt.order_by(Pagina.grupo, Pagina.orden, Pagina.titulo))
    return list(result.all())


async def get_pagina(session: AsyncSession, pagina_id: uuid.UUID, *, lock: bool = False) -> Pagina:
    item = await session.get(Pagina, pagina_id, with_for_update=lock)
    if item is None:
        raise _not_found("La página")
    return item


async def pagina_publicada(session: AsyncSession, slug: str) -> Pagina:
    item = await session.scalar(
        select(Pagina).where(Pagina.slug == slug, Pagina.estado == PUBLICADO)
    )
    if item is None:
        raise _not_found("La página")
    return item


async def _commit_pagina(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Ya hay una página con ese enlace.") from exc


async def crear_pagina(
    session: AsyncSession, ctx: RequestContext, actor: User, data: PaginaIn
) -> Pagina:
    item = Pagina(
        id=uuid.uuid4(),
        slug=data.slug or await _slug_libre(session, Pagina, slugify(data.titulo)),
        grupo=data.grupo.value,
        titulo=data.titulo,
        contenido=data.contenido,
        orden=data.orden,
        estado=EstadoPublicacion.BORRADOR.value,
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_PAGINA_CREADA,
        actor_user_id=actor.id,
        new_value=_valores(item, PAGINA_CAMPOS),
        details={"pagina_id": str(item.id)},
    )
    await _commit_pagina(session)
    await session.refresh(item)
    return item


async def actualizar_pagina(
    session: AsyncSession, ctx: RequestContext, actor: User, pagina_id: uuid.UUID, data: PaginaIn
) -> Pagina:
    item = await get_pagina(session, pagina_id, lock=True)
    antes = _valores(item, PAGINA_CAMPOS)
    if data.slug and data.slug != item.slug:
        if item.estado != EstadoPublicacion.BORRADOR.value:
            raise _conflict("El enlace de una página publicada no cambia.")
        item.slug = data.slug
    item.grupo = data.grupo.value
    item.titulo = data.titulo
    item.contenido = data.contenido
    item.orden = data.orden
    despues = _valores(item, PAGINA_CAMPOS)
    cambios = [c for c in PAGINA_CAMPOS if antes[c] != despues[c]]
    if cambios:
        record_audit(
            session,
            ctx,
            AuditEvent.CMS_PAGINA_ACTUALIZADA,
            actor_user_id=actor.id,
            old_value={c: antes[c] for c in cambios},
            new_value={c: despues[c] for c in cambios},
            details={"pagina_id": str(item.id), "estado": item.estado},
        )
    await _commit_pagina(session)
    await session.refresh(item)
    return item


async def estado_pagina(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    pagina_id: uuid.UUID,
    nuevo: EstadoPublicacion,
) -> Pagina:
    item = await get_pagina(session, pagina_id, lock=True)
    anterior = item.estado
    _transicion(anterior, nuevo)
    item.estado = nuevo.value
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_PAGINA_ESTADO,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": anterior},
        new_value={"estado": nuevo.value},
        details={"pagina_id": str(item.id), "slug": item.slug},
    )
    await session.commit()
    await session.refresh(item)
    return item


# --------------------------------------------------------------------------- portada


async def portada_vigente(session: AsyncSession) -> PortadaVersion | None:
    return await session.scalar(
        select(PortadaVersion)
        .order_by(PortadaVersion.created_at.desc(), PortadaVersion.id.desc())
        .limit(1)
    )


def configuracion(data: PortadaIn) -> dict[str, Any]:
    return {
        "destacadas": [str(n) for n in data.destacadas],
        "filas": [
            {
                "distribucion": f.distribucion.value,
                "notas": [str(n) if n else None for n in f.notas],
            }
            for f in data.filas
        ],
    }


def leer_configuracion(config: dict[str, Any]) -> PortadaIn:
    return PortadaIn.model_validate(config)


async def guardar_portada(
    session: AsyncSession, ctx: RequestContext, actor: User, data: PortadaIn
) -> PortadaVersion:
    if len(set(data.destacadas)) != len(data.destacadas):
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Una nota aparece dos veces entre las destacadas."
        )
    usadas: set[uuid.UUID] = set()
    for i, fila in enumerate(data.filas, start=1):
        if len(fila.notas) != len(ANCHOS[fila.distribucion]):
            raise ProblemError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"La fila {i} ({fila.distribucion.value}) tiene"
                f" {len(ANCHOS[fila.distribucion])} espacios para notas.",
            )
        for nota in fila.notas:
            if nota is None:
                continue
            if nota in usadas:
                raise ProblemError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "Una nota aparece dos veces en las filas de la portada.",
                )
            usadas.add(nota)
    ids = usadas | set(data.destacadas)
    if ids:
        existentes = set(
            (await session.scalars(select(Novedad.id).where(Novedad.id.in_(ids)))).all()
        )
        if faltan := ids - existentes:
            raise ProblemError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"La portada usa {len(faltan)} nota(s) que no existen.",
            )
    anterior = await portada_vigente(session)
    nueva = PortadaVersion(
        id=uuid.uuid4(), configuracion=configuracion(data), creado_por_user_id=actor.id
    )
    session.add(nueva)
    record_audit(
        session,
        ctx,
        AuditEvent.CMS_PORTADA_ACTUALIZADA,
        actor_user_id=actor.id,
        old_value=anterior.configuracion if anterior else None,
        new_value=nueva.configuracion,
        details={"portada_version_id": str(nueva.id)},
    )
    await session.commit()
    await session.refresh(nueva)
    return nueva


async def novedades_por_id(
    session: AsyncSession, ids: set[uuid.UUID], *, solo_publicadas: bool
) -> dict[uuid.UUID, Novedad]:
    if not ids:
        return {}
    stmt = select(Novedad).where(Novedad.id.in_(ids))
    if solo_publicadas:
        stmt = stmt.where(Novedad.estado == PUBLICADO)
    return {n.id: n for n in (await session.scalars(stmt)).all()}
