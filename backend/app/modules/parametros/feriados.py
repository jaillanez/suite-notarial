"""Calendario de feriados nacionales (Caja, 26/11/2026).

En un feriado nacional no se autorizan escrituras ni se acreditan pagos, como en sábado y
domingo. Los provinciales no cuentan. La Caja carga cada feriado; ninguno se inventa en el
código. No se borran (INM): se dan de baja con motivo y todo queda en la auditoría.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, record_audit
from app.core.errors import ProblemError
from app.modules.iam.models import User
from app.modules.parametros.models import Feriado

# date.weekday(): 5 es sábado, 6 domingo.
SABADO = 5


async def feriados_entre(session: AsyncSession, desde: date, hasta: date) -> frozenset[date]:
    """Feriados nacionales vigentes entre dos fechas, inclusive."""
    fechas = await session.scalars(
        select(Feriado.fecha).where(
            Feriado.is_active.is_(True), Feriado.fecha >= desde, Feriado.fecha <= hasta
        )
    )
    return frozenset(fechas.all())


async def feriado_en(session: AsyncSession, fecha: date) -> Feriado | None:
    return await session.scalar(
        select(Feriado).where(Feriado.is_active.is_(True), Feriado.fecha == fecha)
    )


def es_habil(fecha: date, feriados: frozenset[date]) -> bool:
    return fecha.weekday() < SABADO and fecha not in feriados


def proximo_habil(fecha: date, feriados: frozenset[date]) -> date:
    while not es_habil(fecha, feriados):
        fecha += timedelta(days=1)
    return fecha


async def listar(session: AsyncSession, anio: int) -> list[Feriado]:
    result = await session.scalars(
        select(Feriado)
        .where(Feriado.fecha >= date(anio, 1, 1), Feriado.fecha <= date(anio, 12, 31))
        .order_by(Feriado.fecha, Feriado.created_at)
    )
    return list(result.all())


def _valores(f: Feriado) -> dict[str, str | bool]:
    return {"fecha": f.fecha.isoformat(), "descripcion": f.descripcion, "is_active": f.is_active}


async def crear(
    session: AsyncSession, ctx: RequestContext, actor: User, fecha: date, descripcion: str
) -> Feriado:
    if fecha.weekday() >= SABADO:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Ese día es sábado o domingo: ya está bloqueado, no hace falta cargarlo.",
        )
    feriado = Feriado(
        id=uuid.uuid4(), fecha=fecha, descripcion=descripcion, created_by_user_id=actor.id
    )
    session.add(feriado)
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_FERIADO_CREADO,
        actor_user_id=actor.id,
        new_value=_valores(feriado) | {"is_active": True},
        details={"feriado_id": str(feriado.id)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ProblemError(
            HTTPStatus.CONFLICT, f"El {fecha:%d/%m/%Y} ya está cargado como feriado."
        ) from exc
    return feriado


async def dar_de_baja(
    session: AsyncSession, ctx: RequestContext, actor: User, feriado_id: uuid.UUID, motivo: str
) -> Feriado:
    feriado = await session.get(Feriado, feriado_id, with_for_update=True)
    if feriado is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El feriado no existe.")
    if not feriado.is_active:
        raise ProblemError(HTTPStatus.CONFLICT, "El feriado ya está dado de baja.")
    antes = _valores(feriado)
    feriado.is_active = False
    feriado.baja_por_user_id = actor.id
    feriado.baja_motivo = motivo
    feriado.baja_en = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_FERIADO_BAJA,
        actor_user_id=actor.id,
        old_value=antes,
        new_value=_valores(feriado),
        details={"feriado_id": str(feriado.id), "motivo": motivo},
    )
    await session.commit()
    return feriado
