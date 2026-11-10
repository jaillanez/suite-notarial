"""Licencias de escribanos: deja de ejercer un tiempo y vuelve; su cargo sigue siendo suyo.

Una licencia no cambia el estado de la matrícula ni cierra cargos. Mientras dure, el registro
del titular puede quedar a cargo de otro escribano: eso es una designación «a cargo»
(`a_cargo.py`), que convive con la licencia y no se fusiona con ella.

Nada se borra (INM): una licencia se termina (fecha de regreso) o se anula con motivo. Todo
cambio se audita con valor anterior y nuevo (AUD).
"""

import uuid
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.core.errors import ProblemError
from app.modules.iam.models import User
from app.modules.padron.catalog import ESTADOS_DEFINITIVOS, EstadoMatricula
from app.modules.padron.models import Escribano, Licencia
from app.modules.padron.schemas import LicenciaAnulacion, LicenciaFin, LicenciaIn

SOLAPAMIENTO = "ex_padron_licencias_sin_solapamiento"
CAMPOS = ("fecha_desde", "fecha_hasta", "motivo", "resolucion_respaldo", "anulada")


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _invalid(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, message)


def _snapshot(item: Licencia) -> dict[str, Any]:
    datos: dict[str, Any] = {}
    for campo in CAMPOS:
        valor = getattr(item, campo)
        datos[campo] = valor.isoformat() if isinstance(valor, date) else valor
    return datos


def rige(item: Licencia, hoy: date) -> bool:
    """No anulada y con `hoy` dentro del rango (fecha_hasta NULL = sin fecha de regreso)."""
    return (
        not item.anulada
        and item.fecha_desde <= hoy
        and (item.fecha_hasta is None or hoy <= item.fecha_hasta)
    )


def _texto_rango(item: Licencia) -> str:
    hasta = f"{item.fecha_hasta:%d/%m/%Y}" if item.fecha_hasta else "sin fecha de regreso"
    return f"del {item.fecha_desde:%d/%m/%Y} ({hasta})"


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        if constraint == SOLAPAMIENTO:
            raise _conflict("La licencia se superpone con otra del escribano.") from exc
        raise


async def _escribano(session: AsyncSession, escribano_id: uuid.UUID) -> Escribano:
    # Bloquea al escribano: dos altas simultáneas no pueden saltear el control de solapamiento.
    result = await session.execute(
        select(Escribano).where(Escribano.id == escribano_id).with_for_update(of=Escribano)
    )
    item = result.unique().scalars().first()
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El escribano no existe.")
    return item


async def _licencia(session: AsyncSession, licencia_id: uuid.UUID) -> Licencia:
    item = await session.get(Licencia, licencia_id)
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La licencia no existe.")
    await _escribano(session, item.escribano_id)
    await session.refresh(item)
    return item


async def listar(
    session: AsyncSession, escribano_id: uuid.UUID
) -> list[tuple[Licencia, str | None]]:
    """Historia completa (anuladas incluidas), de la más reciente a la más antigua."""
    result = await session.execute(
        select(Licencia, User.email)
        .outerjoin(User, User.id == Licencia.created_by_user_id)
        .where(Licencia.escribano_id == escribano_id)
        .order_by(Licencia.fecha_desde.desc(), Licencia.created_at.desc())
    )
    return [(row, email) for row, email in result.all()]


async def vigentes(
    session: AsyncSession, escribano_ids: list[uuid.UUID], hoy: date | None = None
) -> dict[uuid.UUID, date]:
    """Inicio de la licencia que rige hoy, por escribano (para listados y fichas)."""
    if not escribano_ids:
        return {}
    dia = hoy or today_local()
    result = await session.execute(
        select(Licencia.escribano_id, Licencia.fecha_desde).where(
            Licencia.escribano_id.in_(escribano_ids),
            Licencia.anulada.is_(False),
            Licencia.fecha_desde <= dia,
            (Licencia.fecha_hasta.is_(None)) | (Licencia.fecha_hasta >= dia),
        )
    )
    return {escribano_id: desde for escribano_id, desde in result.all()}


async def _sin_solapamiento(
    session: AsyncSession,
    escribano_id: uuid.UUID,
    desde: date,
    hasta: date | None,
    excluir: uuid.UUID | None = None,
) -> None:
    stmt = select(Licencia).where(
        Licencia.escribano_id == escribano_id,
        Licencia.anulada.is_(False),
        (Licencia.fecha_hasta.is_(None)) | (Licencia.fecha_hasta >= desde),
    )
    if hasta is not None:
        stmt = stmt.where(Licencia.fecha_desde <= hasta)
    if excluir is not None:
        stmt = stmt.where(Licencia.id != excluir)
    otra = (await session.execute(stmt.limit(1))).scalars().first()
    if otra is not None:
        raise _conflict(f"Se superpone con la licencia {_texto_rango(otra)}.")


async def iniciar(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano_id: uuid.UUID,
    data: LicenciaIn,
) -> Licencia:
    escribano = await _escribano(session, escribano_id)
    hoy = today_local()
    sigue = data.fecha_hasta is None or data.fecha_hasta >= hoy
    estado = EstadoMatricula(escribano.estado_matricula)
    if sigue and estado in ESTADOS_DEFINITIVOS:
        # Una licencia pasada (con regreso) se puede registrar como historia; una que sigue,
        # no: quien dejó de ejercer no está de licencia.
        raise _conflict(
            f"La matrícula está en estado {estado.value}: no puede tener una licencia vigente."
        )
    juramento = escribano.fecha_matriculacion
    if juramento is not None and data.fecha_desde < juramento:
        raise _invalid(f"La licencia no puede empezar antes del juramento ({juramento:%d/%m/%Y}).")
    await _sin_solapamiento(session, escribano.id, data.fecha_desde, data.fecha_hasta)
    item = Licencia(
        id=uuid.uuid4(),
        escribano_id=escribano.id,
        fecha_desde=data.fecha_desde,
        fecha_hasta=data.fecha_hasta,
        motivo=data.motivo,
        resolucion_respaldo=data.resolucion_respaldo,
        anulada=False,
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_LICENCIA_INICIADA,
        actor_user_id=actor.id,
        new_value=_snapshot(item),
        details={"escribano_id": str(escribano.id), "licencia_id": str(item.id)},
    )
    await _commit(session)
    return item


async def terminar(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    licencia_id: uuid.UUID,
    data: LicenciaFin,
) -> Licencia:
    """Fija (o adelanta) la fecha de regreso. No se extiende: una prórroga es otra licencia."""
    item = await _licencia(session, licencia_id)
    if item.anulada:
        raise _conflict("La licencia está anulada.")
    if item.fecha_hasta is not None and data.fecha_hasta >= item.fecha_hasta:
        raise _conflict(
            f"La licencia ya termina el {item.fecha_hasta:%d/%m/%Y}: solo se puede adelantar."
        )
    if data.fecha_hasta < item.fecha_desde:
        raise _invalid("La fecha de regreso no puede ser anterior al inicio de la licencia.")
    old = _snapshot(item)
    item.fecha_hasta = data.fecha_hasta
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_LICENCIA_TERMINADA,
        actor_user_id=actor.id,
        old_value=old,
        new_value=_snapshot(item),
        details={"escribano_id": str(item.escribano_id), "licencia_id": str(item.id)},
    )
    await _commit(session)
    return item


async def anular(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    licencia_id: uuid.UUID,
    data: LicenciaAnulacion,
) -> Licencia:
    """Una licencia cargada por error: queda en la historia, marcada como anulada."""
    item = await _licencia(session, licencia_id)
    if item.anulada:
        raise _conflict("La licencia ya está anulada.")
    old = _snapshot(item)
    item.anulada = True
    item.motivo_anulacion = data.motivo
    item.anulada_por_user_id = actor.id
    item.anulada_en = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_LICENCIA_ANULADA,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value=old,
        new_value=_snapshot(item),
        details={
            "escribano_id": str(item.escribano_id),
            "licencia_id": str(item.id),
            "motivo": data.motivo,
        },
    )
    await _commit(session)
    return item
