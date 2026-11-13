"""Vademécum de aportes: cómo aporta cada acto (Caja Notarial, Asamblea del 19/05/2026).

Cada fila es un acto con su categoría (variable, fijo mayor, fijo menor o exento) y su vigencia.
Como las vigencias del motor paramétrico, cambia el dinero que se cobra, así que tiene el mismo
control de cuatro ojos: quien la carga la deja PENDIENTE_APROBACION y otra persona la aprueba o
la rechaza. Solo las aprobadas rigen. Una versión nunca se modifica ni se borra (trigger): un
cambio es una versión nueva del mismo código que, al aprobarse, cierra la anterior el día previo
a su inicio. Un cambio sobre un acto que ya rige empieza mañana o después, para no alterar DDJJ
en carga; las DDJJ presentadas conservan la versión con que se valorizaron (SNAP).

Los montos no viven acá: salen del motor paramétrico según la categoría.
TODO(negocio): retirar un acto del vademécum (hoy no se ofrece: sería un cambio de una sola
persona). Si la Caja lo necesita, se agrega como propuesta que aprueba otra persona.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.core.errors import ProblemError
from app.modules.ddjj.catalog import CategoriaActo, MotivoExencion
from app.modules.ddjj.models import VademecumActo
from app.modules.ddjj.schemas import VademecumIn
from app.modules.iam.models import User
from app.modules.parametros.catalog import EstadoVigencia

# Categorías que admite el vademécum (SIN_EFECTO no es un acto: es una escritura no usada).
CATEGORIAS = (
    CategoriaActo.ESCRITURA_CON_VALOR,
    CategoriaActo.OTRO_ACTO,
    CategoriaActo.ACTA_O_PODER,
    CategoriaActo.EXENTO,
)
# Exenciones que nombra el vademécum («otro motivo» queda para actos fuera de él).
MOTIVOS = (
    MotivoExencion.ACTA_SUBSANATORIA,
    MotivoExencion.CONVENIO_IPV,
    MotivoExencion.ASOCIACION_INTERMEDIA_IPV,
    MotivoExencion.REGULACION_DOMINIAL,
)
CAMPOS = (
    "codigo",
    "version",
    "nombre",
    "categoria",
    "motivo_exencion",
    "aclaracion",
    "sinonimos",
    "orden",
    "fecha_desde",
    "fecha_hasta",
    "resolucion",
    "estado",
)
VIGENTE = EstadoVigencia.VIGENTE.value
PENDIENTE = EstadoVigencia.PENDIENTE_APROBACION.value


def valores(item: VademecumActo) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for campo in CAMPOS:
        valor = getattr(item, campo)
        out[campo] = valor.isoformat() if isinstance(valor, date) else valor
    return out


def vigente_el(item: VademecumActo, fecha: date) -> bool:
    return (
        item.estado == VIGENTE
        and item.fecha_desde <= fecha
        and (item.fecha_hasta is None or fecha <= item.fecha_hasta)
    )


async def vigentes(session: AsyncSession, fecha: date) -> list[VademecumActo]:
    """Los actos aprobados que rigen el día indicado, en el orden del documento."""
    result = await session.execute(
        select(VademecumActo)
        .where(
            VademecumActo.estado == VIGENTE,
            VademecumActo.fecha_desde <= fecha,
            or_(VademecumActo.fecha_hasta.is_(None), VademecumActo.fecha_hasta >= fecha),
        )
        .order_by(VademecumActo.orden, VademecumActo.nombre)
    )
    return list(result.scalars())


async def pendientes(session: AsyncSession) -> list[VademecumActo]:
    """Propuestas que esperan la aprobación de otra persona."""
    result = await session.execute(
        select(VademecumActo)
        .where(VademecumActo.estado == PENDIENTE)
        .order_by(VademecumActo.orden, VademecumActo.codigo, VademecumActo.version)
    )
    return list(result.scalars())


def _validar(data: VademecumIn) -> None:
    if data.categoria not in CATEGORIAS:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Esa categoría no corresponde a un acto del vademécum."
        )
    exento = data.categoria is CategoriaActo.EXENTO
    if exento and data.motivo_exencion not in MOTIVOS:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Un acto exento indica cuál exención del vademécum."
        )
    if not exento and data.motivo_exencion is not None:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Solo un acto exento lleva motivo de exención."
        )


async def _versiones(
    session: AsyncSession, codigo: str, *, lock: bool = False
) -> list[VademecumActo]:
    query = (
        select(VademecumActo).where(VademecumActo.codigo == codigo).order_by(VademecumActo.version)
    )
    if lock:
        query = query.with_for_update()
    return list((await session.execute(query)).scalars())


def _controlar_fecha(item_codigo: str, desde: date, anteriores: list[VademecumActo]) -> None:
    """Una versión nueva empieza después de todas las aprobadas, y un cambio sobre un acto que
    ya rige empieza mañana o después (no reescribe períodos en curso)."""
    aprobadas = [v for v in anteriores if v.estado == VIGENTE]
    for v in aprobadas:
        if v.fecha_desde >= desde or (v.fecha_hasta is not None and v.fecha_hasta >= desde):
            raise ProblemError(
                HTTPStatus.CONFLICT,
                f"La versión {v.version} de {item_codigo} ya rige desde el "
                f"{v.fecha_desde:%d/%m/%Y}: la nueva tiene que empezar después.",
            )
    if aprobadas and desde <= today_local():
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "Un cambio sobre un acto que ya rige empieza mañana o después: las declaraciones en "
            "carga no cambian de golpe.",
        )


async def proponer(
    session: AsyncSession, ctx: RequestContext, actor: User, data: VademecumIn
) -> VademecumActo:
    """Propone un acto nuevo o una versión nueva de uno existente. Queda pendiente."""
    _validar(data)
    anteriores = await _versiones(session, data.codigo, lock=True)
    if any(v.estado == PENDIENTE for v in anteriores):
        raise ProblemError(
            HTTPStatus.CONFLICT,
            f"{data.codigo} ya tiene una propuesta pendiente: que la aprueben o la rechacen antes.",
        )
    _controlar_fecha(data.codigo, data.fecha_desde, anteriores)
    version = (
        await session.scalar(
            select(func.coalesce(func.max(VademecumActo.version), 0)).where(
                VademecumActo.codigo == data.codigo
            )
        )
        or 0
    ) + 1
    item = VademecumActo(
        id=uuid.uuid4(),
        codigo=data.codigo,
        version=version,
        nombre=data.nombre,
        categoria=data.categoria.value,
        motivo_exencion=data.motivo_exencion.value if data.motivo_exencion else None,
        aclaracion=data.aclaracion,
        sinonimos=data.sinonimos,
        orden=data.orden,
        fecha_desde=data.fecha_desde,
        resolucion=data.resolucion,
        estado=PENDIENTE,
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.VADEMECUM_ACTO_PROPUESTO,
        actor_user_id=actor.id,
        new_value=valores(item),
        details={"vademecum_id": str(item.id), "motivo": data.motivo},
    )
    await session.commit()
    return item


async def _pendiente(session: AsyncSession, item_id: uuid.UUID, actor: User) -> VademecumActo:
    result = await session.execute(
        select(VademecumActo).where(VademecumActo.id == item_id).with_for_update()
    )
    item = result.scalars().first()
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El acto del vademécum no existe.")
    if item.estado != PENDIENTE:
        raise ProblemError(HTTPStatus.CONFLICT, "Esa versión no está pendiente de aprobación.")
    if item.created_by_user_id == actor.id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Quien propone un cambio del vademécum no puede aprobarlo: lo aprueba otra persona.",
            type_="urn:suite-notarial:parametros:cuatro-ojos",
        )
    return item


async def aprobar(
    session: AsyncSession, ctx: RequestContext, actor: User, item_ids: list[uuid.UUID]
) -> list[VademecumActo]:
    """Aprueba propuestas de otra persona. Cada una cierra la versión que reemplaza el día
    anterior a su inicio. Se aprueban todas o ninguna."""
    aprobadas = []
    for item_id in item_ids:
        item = await _pendiente(session, item_id, actor)
        anteriores = [v for v in await _versiones(session, item.codigo, lock=True) if v is not item]
        # La fecha se controla otra vez: pudo pasar el día mientras esperaba.
        _controlar_fecha(item.codigo, item.fecha_desde, anteriores)
        abierta = next(
            (v for v in anteriores if v.estado == VIGENTE and v.fecha_hasta is None), None
        )
        if abierta is not None:
            cierre = item.fecha_desde - timedelta(days=1)
            abierta.fecha_hasta = cierre
            record_audit(
                session,
                ctx,
                AuditEvent.VADEMECUM_ACTO_CERRADO,
                actor_user_id=actor.id,
                old_value={"fecha_hasta": None},
                new_value={"fecha_hasta": cierre.isoformat()},
                details={"vademecum_id": str(abierta.id), "reemplazada_por": str(item.id)},
            )
            await session.flush()
        item.estado = VIGENTE
        item.aprobado_por_user_id = actor.id
        item.fecha_aprobacion = datetime.now(UTC)
        record_audit(
            session,
            ctx,
            AuditEvent.VADEMECUM_ACTO_APROBADO,
            severity=Severity.WARNING,
            actor_user_id=actor.id,
            old_value={"estado": PENDIENTE},
            new_value=valores(item),
            details={"vademecum_id": str(item.id), "propuesto_por": str(item.created_by_user_id)},
        )
        await session.flush()
        aprobadas.append(item)
    await session.commit()
    return aprobadas


async def rechazar(
    session: AsyncSession, ctx: RequestContext, actor: User, item_id: uuid.UUID, motivo: str
) -> VademecumActo:
    item = await _pendiente(session, item_id, actor)
    item.estado = EstadoVigencia.RECHAZADA.value
    record_audit(
        session,
        ctx,
        AuditEvent.VADEMECUM_ACTO_RECHAZADO,
        actor_user_id=actor.id,
        old_value={"estado": PENDIENTE},
        new_value={"estado": item.estado},
        details={"vademecum_id": str(item.id), "motivo": motivo},
    )
    await session.commit()
    return item
