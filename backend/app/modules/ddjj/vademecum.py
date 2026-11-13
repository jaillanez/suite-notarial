"""Vademécum de aportes: cómo aporta cada acto (Caja Notarial, Asamblea del 19/05/2026).

Cada fila es un acto con su categoría (variable, fijo mayor, fijo menor o exento) y su vigencia.
Nunca se modifica ni se borra (trigger): un cambio es una versión nueva del mismo código, que
cierra la anterior el día previo a su inicio, y una baja es cerrar la vigencia. Todo queda en la
auditoría. Los montos no viven acá: salen del motor paramétrico según la categoría.

TODO(negocio): hoy edita quien puede proponer parámetros (`parameters:write`), sin aprobación
de una segunda persona: si la Caja la quiere también acá, se agrega como en las vigencias.
"""

import uuid
from datetime import date, timedelta
from http import HTTPStatus
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.core.errors import ProblemError
from app.modules.ddjj.catalog import CategoriaActo, MotivoExencion
from app.modules.ddjj.models import VademecumActo
from app.modules.ddjj.schemas import VademecumBajaIn, VademecumIn
from app.modules.iam.models import User

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
)


def valores(item: VademecumActo) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for campo in CAMPOS:
        valor = getattr(item, campo)
        out[campo] = valor.isoformat() if isinstance(valor, date) else valor
    return out


def vigente_el(item: VademecumActo, fecha: date) -> bool:
    return item.fecha_desde <= fecha and (item.fecha_hasta is None or fecha <= item.fecha_hasta)


async def vigentes(session: AsyncSession, fecha: date) -> list[VademecumActo]:
    """Los actos del vademécum que rigen el día indicado, en el orden del documento."""
    result = await session.execute(
        select(VademecumActo)
        .where(
            VademecumActo.fecha_desde <= fecha,
            or_(VademecumActo.fecha_hasta.is_(None), VademecumActo.fecha_hasta >= fecha),
        )
        .order_by(VademecumActo.orden, VademecumActo.nombre)
    )
    return list(result.scalars())


async def historial(session: AsyncSession) -> list[VademecumActo]:
    """Todas las versiones de todos los actos (para la administración)."""
    result = await session.execute(
        select(VademecumActo).order_by(
            VademecumActo.orden, VademecumActo.codigo, VademecumActo.version.desc()
        )
    )
    return list(result.scalars())


async def get(session: AsyncSession, item_id: uuid.UUID) -> VademecumActo:
    item = await session.get(VademecumActo, item_id)
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El acto del vademécum no existe.")
    return item


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


async def agregar(
    session: AsyncSession, ctx: RequestContext, actor: User, data: VademecumIn
) -> VademecumActo:
    """Versión nueva de un acto (o su primera versión).

    Si el código ya rige, la versión vigente se cierra el día anterior al inicio de la nueva.
    No se puede empezar antes ni el mismo día que una versión que ya empezó: los actos
    declarados con ella no cambian (SNAP); para corregir, se agrega otra versión hacia adelante.
    """
    _validar(data)
    anteriores = await _versiones(session, data.codigo, lock=True)
    abierta = next((v for v in anteriores if v.fecha_hasta is None), None)
    for v in anteriores:
        if v.fecha_desde >= data.fecha_desde:
            raise ProblemError(
                HTTPStatus.CONFLICT,
                f"La versión {v.version} de {data.codigo} ya rige desde el "
                f"{v.fecha_desde:%d/%m/%Y}: la nueva tiene que empezar después.",
            )
        if v.fecha_hasta is not None and v.fecha_hasta >= data.fecha_desde:
            raise ProblemError(
                HTTPStatus.CONFLICT,
                f"La versión {v.version} de {data.codigo} rige hasta el "
                f"{v.fecha_hasta:%d/%m/%Y}: la nueva tiene que empezar después.",
            )
    if abierta is not None:
        cierre = data.fecha_desde - timedelta(days=1)
        abierta.fecha_hasta = cierre
        record_audit(
            session,
            ctx,
            AuditEvent.VADEMECUM_ACTO_CERRADO,
            actor_user_id=actor.id,
            old_value={"fecha_hasta": None},
            new_value={"fecha_hasta": cierre.isoformat()},
            details={
                "vademecum_id": str(abierta.id),
                "codigo": abierta.codigo,
                "motivo": data.motivo,
            },
        )
        await session.flush()
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
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.VADEMECUM_ACTO_AGREGADO,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        new_value=valores(item),
        details={"vademecum_id": str(item.id), "motivo": data.motivo},
    )
    await session.commit()
    return item


async def dar_de_baja(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    item_id: uuid.UUID,
    data: VademecumBajaIn,
) -> VademecumActo:
    """Deja de regir desde una fecha: la vigencia se cierra el día anterior."""
    result = await session.execute(
        select(VademecumActo).where(VademecumActo.id == item_id).with_for_update()
    )
    item = result.scalars().first()
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El acto del vademécum no existe.")
    if item.fecha_hasta is not None:
        raise ProblemError(HTTPStatus.CONFLICT, "Esa versión ya tiene fecha de fin.")
    cierre = data.desde - timedelta(days=1)
    if cierre < item.fecha_desde:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            f"La versión rige desde el {item.fecha_desde:%d/%m/%Y}: la baja tiene que ser "
            "posterior.",
        )
    item.fecha_hasta = cierre
    record_audit(
        session,
        ctx,
        AuditEvent.VADEMECUM_ACTO_CERRADO,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"fecha_hasta": None},
        new_value={"fecha_hasta": cierre.isoformat()},
        details={"vademecum_id": str(item.id), "codigo": item.codigo, "motivo": data.motivo},
    )
    await session.commit()
    return item
