"""Documentación de las solicitudes de préstamo (Anexo I: carga de la documentación requerida).

- Los archivos se validan y guardan como los comprobantes (regla MIME): magic bytes, tamaño
  máximo, nombre UUID fuera del webroot y huella SHA-256 verificada al descargar.
- La ven el titular y el personal que ve todos los préstamos; el garante no (es la situación
  económica del titular).
- Cargan el titular y quien administra préstamos, solo mientras la solicitud está abierta.
- Nada se borra (regla INM): un documento cargado por error se anula con motivo y deja de
  contar para la documentación requerida. Lo puede anular quien lo cargó o quien administra
  préstamos, también solo con la solicitud abierta.
"""

import uuid
from datetime import UTC, datetime
from http import HTTPStatus

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.pagos import storage
from app.modules.prestamos import service
from app.modules.prestamos.catalog import EstadoPrestamo, TipoDocumento
from app.modules.prestamos.models import DocumentoPrestamo, Prestamo

SUBDIR = "prestamos"
ABIERTA = EstadoPrestamo.SOLICITADO.value


def _gestiona(principal: Principal) -> bool:
    return Perm.PRESTAMOS_MANAGE.value in principal.permissions


async def es_titular(session: AsyncSession, principal: Principal, prestamo: Prestamo) -> bool:
    propio = await service.escribano_de(session, principal.user)
    return propio is not None and propio.id == prestamo.escribano_id


async def puede_ver(session: AsyncSession, principal: Principal, prestamo: Prestamo) -> bool:
    return service.ve_todo(principal) or await es_titular(session, principal, prestamo)


async def puede_cargar(session: AsyncSession, principal: Principal, prestamo: Prestamo) -> bool:
    return prestamo.estado == ABIERTA and (
        _gestiona(principal) or await es_titular(session, principal, prestamo)
    )


def puede_anular(principal: Principal, prestamo: Prestamo, doc: DocumentoPrestamo) -> bool:
    return (
        prestamo.estado == ABIERTA
        and doc.anulado_en is None
        and (_gestiona(principal) or doc.subido_por_user_id == principal.user.id)
    )


async def _prestamo_visible(
    session: AsyncSession, principal: Principal, prestamo_id: uuid.UUID, *, lock: bool = False
) -> Prestamo:
    prestamo = await service.get_prestamo(session, principal, prestamo_id, lock=lock)
    if not await puede_ver(session, principal, prestamo):
        # El garante ve el préstamo pero no su documentación.
        raise ProblemError(HTTPStatus.NOT_FOUND, "La documentación del préstamo no existe.")
    return prestamo


async def listar(session: AsyncSession, prestamo_id: uuid.UUID) -> list[DocumentoPrestamo]:
    result = await session.scalars(
        select(DocumentoPrestamo)
        .where(DocumentoPrestamo.prestamo_id == prestamo_id)
        .order_by(DocumentoPrestamo.created_at, DocumentoPrestamo.id)
    )
    return list(result.all())


async def cargar(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    principal: Principal,
    prestamo_id: uuid.UUID,
    tipo: TipoDocumento,
    descripcion: str | None,
    archivo: storage.ArchivoValidado,
) -> DocumentoPrestamo:
    prestamo = await _prestamo_visible(session, principal, prestamo_id, lock=True)
    if prestamo.estado != ABIERTA:
        raise ProblemError(
            HTTPStatus.CONFLICT, "La solicitud ya fue resuelta: su documentación no cambia."
        )
    if not await puede_cargar(session, principal, prestamo):
        raise ProblemError(HTTPStatus.FORBIDDEN, "No podés cargar documentación en este préstamo.")
    if tipo is TipoDocumento.OTRO and not descripcion:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Indicá qué documento es en la descripción."
        )
    relativa = await storage.guardar(settings, archivo, today_local(), subdir=SUBDIR)
    doc = DocumentoPrestamo(
        id=uuid.uuid4(),
        prestamo_id=prestamo.id,
        tipo=tipo.value,
        descripcion=descripcion,
        nombre_original=archivo.nombre_original,
        archivo=relativa,
        mime_type=archivo.mime_type,
        tamano_bytes=archivo.tamano,
        sha256=archivo.sha256,
        subido_por_user_id=principal.user.id,
    )
    session.add(doc)
    record_audit(
        session,
        ctx,
        AuditEvent.PRESTAMO_DOCUMENTO_CARGADO,
        actor_user_id=principal.user.id,
        new_value={
            "tipo": tipo.value,
            "descripcion": descripcion,
            "sha256": archivo.sha256,
            "mime_type": archivo.mime_type,
            "tamano_bytes": archivo.tamano,
        },
        details={
            "prestamo_id": str(prestamo.id),
            "numero": prestamo.numero,
            "documento_id": str(doc.id),
        },
    )
    try:
        await session.commit()
    except BaseException:
        await storage.eliminar(settings, relativa)
        raise
    await session.refresh(doc)
    return doc


async def _documento(
    session: AsyncSession, prestamo: Prestamo, documento_id: uuid.UUID, *, lock: bool = False
) -> DocumentoPrestamo:
    doc = await session.get(DocumentoPrestamo, documento_id, with_for_update=lock)
    if doc is None or doc.prestamo_id != prestamo.id:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El documento no existe.")
    return doc


async def anular(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    prestamo_id: uuid.UUID,
    documento_id: uuid.UUID,
    motivo: str,
) -> DocumentoPrestamo:
    prestamo = await _prestamo_visible(session, principal, prestamo_id, lock=True)
    doc = await _documento(session, prestamo, documento_id, lock=True)
    if doc.anulado_en is not None:
        raise ProblemError(HTTPStatus.CONFLICT, "El documento ya está anulado.")
    if prestamo.estado != ABIERTA:
        raise ProblemError(
            HTTPStatus.CONFLICT, "La solicitud ya fue resuelta: su documentación no cambia."
        )
    if not puede_anular(principal, prestamo, doc):
        raise ProblemError(
            HTTPStatus.FORBIDDEN, "Solo quien lo cargó o la Caja pueden anular este documento."
        )
    doc.anulado_en = datetime.now(UTC)
    doc.anulado_por_user_id = principal.user.id
    doc.motivo_anulacion = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.PRESTAMO_DOCUMENTO_ANULADO,
        actor_user_id=principal.user.id,
        old_value={"anulado": False},
        new_value={"anulado": True, "motivo": motivo},
        details={
            "prestamo_id": str(prestamo.id),
            "numero": prestamo.numero,
            "documento_id": str(doc.id),
            "tipo": doc.tipo,
        },
    )
    await session.commit()
    await session.refresh(doc)
    return doc


async def contenido(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    principal: Principal,
    prestamo_id: uuid.UUID,
    documento_id: uuid.UUID,
) -> tuple[DocumentoPrestamo, bytes]:
    """Archivo verificado contra su huella. Si no coincide, se audita y no se entrega."""
    prestamo = await _prestamo_visible(session, principal, prestamo_id)
    doc = await _documento(session, prestamo, documento_id)
    try:
        return doc, await storage.leer(settings, doc.archivo, doc.sha256)
    except (storage.ArchivoAlteradoError, FileNotFoundError) as exc:
        record_audit(
            session,
            ctx,
            AuditEvent.PRESTAMO_DOCUMENTO_ALTERADO,
            severity=Severity.CRITICAL,
            actor_user_id=principal.user.id,
            details={"documento_id": str(doc.id), "error": type(exc).__name__},
        )
        await session.commit()
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "El archivo no coincide con el original cargado. Se dio aviso a la Caja.",
            type_="urn:suite-notarial:prestamos:documento-alterado",
        ) from exc
