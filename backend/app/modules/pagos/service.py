"""Comprobantes de pago y mesa de conciliación de Tesorería (Módulo 6).

Regla PAGO: adjuntar un comprobante no paga nada. El comprobante queda PENDIENTE_REVISION hasta
que Tesorería (`comprobantes:verify`) lo aprueba, con el importe y la fecha de acreditación que
ve en el extracto, o lo rechaza con motivo. Solo una aprobación pasa la boleta a PAGADA, y la
base lo exige también (trigger sobre `ddjj_boletas`).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.money import format_pesos
from app.common.pagination import PageParams
from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.ddjj import service as ddjj_service
from app.modules.ddjj.catalog import EstadoBoleta
from app.modules.ddjj.models import Boleta
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.iam.models import User
from app.modules.pagos import storage
from app.modules.pagos.catalog import EstadoComprobante, ResultadoConciliacion
from app.modules.pagos.models import Comprobante, Conciliacion
from app.modules.pagos.schemas import AprobacionIn, ComprobanteIn

PENDIENTE = EstadoComprobante.PENDIENTE_REVISION.value


def _not_found() -> ProblemError:
    return ProblemError(HTTPStatus.NOT_FOUND, "El comprobante no existe.")


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _invalid(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, message)


def es_tesoreria(principal: Principal) -> bool:
    return Perm.COMPROBANTES_VERIFY.value in principal.permissions


# --------------------------------------------------------------------------- carga


async def subir(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    principal: Principal,
    boleta_id: uuid.UUID,
    data: ComprobanteIn,
    archivo: storage.ArchivoValidado,
) -> Comprobante:
    """Registra el comprobante de una boleta pendiente propia. Queda en revisión."""
    boleta = await ddjj_service.get_boleta(session, principal, boleta_id, lock=True)
    if boleta.estado != EstadoBoleta.PENDIENTE.value:
        estado = "pagada" if boleta.estado == EstadoBoleta.PAGADA.value else "anulada"
        raise _conflict(f"La boleta N° {boleta.numero} está {estado}: no admite comprobantes.")
    en_revision = await session.scalar(
        select(func.count()).where(
            Comprobante.boleta_id == boleta.id, Comprobante.estado == PENDIENTE
        )
    )
    if en_revision:
        raise _conflict("Ya hay un comprobante de esta boleta en revisión por Tesorería.")
    hoy = today_local()
    if data.fecha_transferencia > hoy:
        raise _invalid("La fecha de la transferencia no puede ser futura.")
    if data.fecha_transferencia < boleta.fecha_emision:
        raise _invalid("La transferencia no puede ser anterior a la emisión de la boleta.")
    if data.importe_declarado <= 0:
        raise _invalid("El importe transferido tiene que ser mayor que cero.")

    relativa = await storage.guardar(settings, archivo, hoy)
    item = Comprobante(
        id=uuid.uuid4(),
        boleta_id=boleta.id,
        registro_id=boleta.registro_id,
        periodo=boleta.periodo,
        nombre_original=archivo.nombre_original,
        archivo=relativa,
        mime_type=archivo.mime_type,
        tamano_bytes=archivo.tamano,
        sha256=archivo.sha256,
        fecha_transferencia=data.fecha_transferencia,
        banco_origen=data.banco_origen,
        numero_operacion=data.numero_operacion,
        importe_declarado=data.importe_declarado,
        estado=PENDIENTE,
        subido_por_user_id=principal.user.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.COMPROBANTE_ADJUNTADO,
        actor_user_id=principal.user.id,
        new_value={
            "estado": PENDIENTE,
            "importe_declarado": f"{data.importe_declarado:.2f}",
            "fecha_transferencia": data.fecha_transferencia.isoformat(),
            "numero_operacion": data.numero_operacion,
            "sha256": archivo.sha256,
            "mime_type": archivo.mime_type,
        },
        details={"comprobante_id": str(item.id), "boleta": boleta.numero},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        await storage.eliminar(settings, relativa)
        raise _conflict("Ya hay un comprobante de esta boleta en revisión por Tesorería.") from exc
    except BaseException:
        await storage.eliminar(settings, relativa)
        raise
    return item


# --------------------------------------------------------------------------- lectura


async def get(
    session: AsyncSession, principal: Principal, comprobante_id: uuid.UUID, *, lock: bool = False
) -> Comprobante:
    item = await session.get(Comprobante, comprobante_id, with_for_update=lock)
    if item is None:
        raise _not_found()
    if es_tesoreria(principal):
        return item
    alcance = await ddjj_service.alcance_boletas(session, principal)
    if alcance is not None and not ddjj_service.incluye(alcance, item.registro_id, item.periodo):
        raise _not_found()
    return item


async def de_boleta(session: AsyncSession, boleta_id: uuid.UUID) -> list[Comprobante]:
    result = await session.scalars(
        select(Comprobante)
        .where(Comprobante.boleta_id == boleta_id)
        .order_by(Comprobante.created_at.desc())
    )
    return list(result.all())


async def ultimos_por_boleta(
    session: AsyncSession, boleta_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Comprobante]:
    """El comprobante más reciente de cada boleta (para mostrar su estado junto a la boleta)."""
    if not boleta_ids:
        return {}
    result = await session.scalars(
        select(Comprobante)
        .where(Comprobante.boleta_id.in_(boleta_ids))
        .order_by(Comprobante.boleta_id, Comprobante.created_at.desc())
        .ext(distinct_on(Comprobante.boleta_id))
    )
    return {c.boleta_id: c for c in result.all()}


async def mesa(
    session: AsyncSession, estado: EstadoComprobante | None, page: PageParams
) -> tuple[list[Comprobante], int]:
    """Bandeja de Tesorería. En revisión, los más antiguos primero (orden de llegada)."""
    stmt = select(Comprobante)
    if estado is not None:
        stmt = stmt.where(Comprobante.estado == estado.value)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    orden = (
        Comprobante.created_at.asc()
        if estado is EstadoComprobante.PENDIENTE_REVISION
        else Comprobante.created_at.desc()
    )
    result = await session.scalars(stmt.order_by(orden).offset(page.offset).limit(page.page_size))
    return list(result.all()), total or 0


async def conciliacion_de(session: AsyncSession, comprobante_id: uuid.UUID) -> Conciliacion | None:
    return await session.scalar(
        select(Conciliacion).where(Conciliacion.comprobante_id == comprobante_id)
    )


async def contar_en_revision(session: AsyncSession) -> int:
    return (await session.scalar(select(func.count()).where(Comprobante.estado == PENDIENTE))) or 0


async def archivo(
    session: AsyncSession, settings: Settings, ctx: RequestContext, actor: User, item: Comprobante
) -> bytes:
    """Contenido verificado contra su huella. Si no coincide, se audita y no se entrega."""
    try:
        return await storage.leer(settings, item.archivo, item.sha256)
    except (storage.ArchivoAlteradoError, FileNotFoundError) as exc:
        record_audit(
            session,
            ctx,
            AuditEvent.COMPROBANTE_ALTERADO,
            severity=Severity.CRITICAL,
            actor_user_id=actor.id,
            details={"comprobante_id": str(item.id), "error": type(exc).__name__},
        )
        await session.commit()
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "El archivo del comprobante no coincide con el original registrado. Se dio aviso a "
            "la Caja.",
            type_="urn:suite-notarial:pagos:archivo-alterado",
        ) from exc


# --------------------------------------------------------------------------- conciliación


@dataclass(frozen=True)
class Resolucion:
    comprobante: Comprobante
    boleta: Boleta
    destinatario: User | None


async def _para_revisar(
    session: AsyncSession, principal: Principal, comprobante_id: uuid.UUID
) -> tuple[Comprobante, Boleta]:
    item = await get(session, principal, comprobante_id, lock=True)
    if item.estado != PENDIENTE:
        raise _conflict("El comprobante ya fue revisado.")
    if item.subido_por_user_id == principal.user.id:
        raise ProblemError(HTTPStatus.FORBIDDEN, "Quien adjuntó el comprobante no puede revisarlo.")
    boleta = await session.get(Boleta, item.boleta_id, with_for_update=True)
    assert boleta is not None  # noqa: S101 - FK RESTRICT
    return item, boleta


def _marcar_revisado(item: Comprobante, actor: User, estado: EstadoComprobante) -> None:
    item.estado = estado.value
    item.revisado_por_user_id = actor.id
    item.revisado_en = datetime.now(UTC)


async def aprobar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    comprobante_id: uuid.UUID,
    data: AprobacionIn,
) -> Resolucion:
    item, boleta = await _para_revisar(session, principal, comprobante_id)
    if boleta.estado != EstadoBoleta.PENDIENTE.value:
        raise _conflict("La boleta ya no está pendiente: rechazá el comprobante indicando por qué.")
    # TODO(negocio): pagos parciales o con diferencia (a favor o en contra). Por ahora solo se
    # aprueba un pago por el total exacto; cualquier otro caso se rechaza con motivo.
    if data.importe_confirmado != boleta.total_a_pagar:
        acreditado = format_pesos(data.importe_confirmado)
        total = format_pesos(boleta.total_a_pagar)
        raise _invalid(
            f"El importe acreditado ({acreditado}) no coincide con el total de la boleta "
            f"({total}). Si el pago es distinto, rechazá el comprobante indicando la diferencia."
        )
    if data.fecha_acreditacion > today_local():
        raise _invalid("La fecha de acreditación no puede ser futura.")
    if data.fecha_acreditacion < item.fecha_transferencia:
        raise _invalid("La acreditación no puede ser anterior a la transferencia declarada.")
    # TODO(negocio): qué hacer con un pago acreditado después de la fecha de pago de la boleta
    # (mora por los días de diferencia). Hasta definirlo, se exige dejar constancia.
    fuera_de_plazo = data.fecha_acreditacion > boleta.fecha_pago
    if fuera_de_plazo and (data.observaciones is None or len(data.observaciones) < 5):
        raise _invalid(
            "La acreditación es posterior a la fecha de pago de la boleta: dejá constancia en "
            "observaciones."
        )
    session.add(
        Conciliacion(
            comprobante_id=item.id,
            boleta_id=boleta.id,
            resultado=ResultadoConciliacion.APROBADO.value,
            importe_confirmado=data.importe_confirmado,
            fecha_acreditacion=data.fecha_acreditacion,
            identificador_extracto=data.identificador_extracto,
            observaciones=data.observaciones,
            operador_user_id=principal.user.id,
            ip_operador=ctx.ip_address,
        )
    )
    await session.flush()
    _marcar_revisado(item, principal.user, EstadoComprobante.APROBADO)
    boleta.estado = EstadoBoleta.PAGADA.value
    detalles = {
        "comprobante_id": str(item.id),
        "boleta": boleta.numero,
        "importe_confirmado": f"{data.importe_confirmado:.2f}",
        "fecha_acreditacion": data.fecha_acreditacion.isoformat(),
        "identificador_extracto": data.identificador_extracto,
        "fuera_de_plazo": fuera_de_plazo,
    }
    record_audit(
        session,
        ctx,
        AuditEvent.COMPROBANTE_APROBADO,
        severity=Severity.WARNING if fuera_de_plazo else Severity.INFO,
        actor_user_id=principal.user.id,
        target_user_id=item.subido_por_user_id,
        old_value={"estado": PENDIENTE},
        new_value={"estado": EstadoComprobante.APROBADO.value},
        details=detalles,
    )
    record_audit(
        session,
        ctx,
        AuditEvent.BOLETA_PAGADA,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        old_value={"estado": EstadoBoleta.PENDIENTE.value},
        new_value={"estado": EstadoBoleta.PAGADA.value},
        details={"boleta_id": str(boleta.id), **detalles},
    )
    await session.commit()
    return Resolucion(item, boleta, await session.get(User, item.subido_por_user_id))


async def rechazar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    comprobante_id: uuid.UUID,
    motivo: str,
) -> Resolucion:
    item, boleta = await _para_revisar(session, principal, comprobante_id)
    session.add(
        Conciliacion(
            comprobante_id=item.id,
            boleta_id=boleta.id,
            resultado=ResultadoConciliacion.RECHAZADO.value,
            observaciones=motivo,
            operador_user_id=principal.user.id,
            ip_operador=ctx.ip_address,
        )
    )
    await session.flush()
    _marcar_revisado(item, principal.user, EstadoComprobante.RECHAZADO)
    item.motivo_rechazo = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.COMPROBANTE_RECHAZADO,
        actor_user_id=principal.user.id,
        target_user_id=item.subido_por_user_id,
        old_value={"estado": PENDIENTE},
        new_value={"estado": EstadoComprobante.RECHAZADO.value},
        details={"comprobante_id": str(item.id), "boleta": boleta.numero, "motivo": motivo},
    )
    await session.commit()
    return Resolucion(item, boleta, await session.get(User, item.subido_por_user_id))
