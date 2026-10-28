"""Gobierno de parámetros: propuesta, aprobación por otra persona y resolución por fecha.

- Una vigencia nueva es una fila nueva; sus valores nunca cambian (trigger en la base).
- Dos vigencias VIGENTES del mismo concepto no se superponen (exclusión en la base).
- Al aprobar una vigencia, la anterior que estaba abierta se cierra el día previo a su inicio.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.core.errors import ProblemError
from app.modules.iam.models import User
from app.modules.parametros.catalog import EstadoVigencia, PeriodoTasa, ReglaRedondeo, TipoConcepto
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.parametros.motor import VigenciaSnapshot
from app.modules.parametros.schemas import ConceptoIn, ConceptoUpdate, VigenciaIn

# Campos que cada tipo exige y los que no admite.
_FIJO_SOLO = (
    frozenset({"monto_fijo"}),
    frozenset(
        {"porcentaje", "monto_minimo", "monto_maximo", "tasa", "periodo_tasa", "dias_gracia"}
    ),
)
CAMPOS_POR_TIPO: dict[TipoConcepto, tuple[frozenset[str], frozenset[str]]] = {
    TipoConcepto.PORCENTUAL_ACTO: (
        frozenset({"porcentaje"}),
        frozenset({"monto_fijo", "tasa", "periodo_tasa", "dias_gracia"}),
    ),
    TipoConcepto.FIJO_ACTO: _FIJO_SOLO,
    TipoConcepto.FIJO_MENSUAL: _FIJO_SOLO,
    TipoConcepto.TASA_MORA: (
        frozenset({"tasa", "periodo_tasa", "dias_gracia"}),
        frozenset({"porcentaje", "monto_fijo", "monto_minimo", "monto_maximo"}),
    ),
}
VALUE_FIELDS = (
    "fecha_desde",
    "fecha_hasta",
    "porcentaje",
    "monto_fijo",
    "monto_minimo",
    "monto_maximo",
    "tasa",
    "periodo_tasa",
    "dias_gracia",
    "regla_redondeo",
    "es_ejemplo",
    "resolucion_respaldo",
)


def _json(value: object) -> object:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | str):
        return value
    return str(value)


def vigencia_values(v: Vigencia) -> dict[str, Any]:
    return {f: _json(getattr(v, f)) for f in VALUE_FIELDS}


def snapshot(v: Vigencia) -> VigenciaSnapshot:
    return VigenciaSnapshot(
        vigencia_id=v.id,
        concepto_codigo=v.concepto.codigo,
        tipo=TipoConcepto(v.concepto.tipo),
        fecha_desde=v.fecha_desde,
        fecha_hasta=v.fecha_hasta,
        porcentaje=v.porcentaje,
        monto_fijo=v.monto_fijo,
        monto_minimo=v.monto_minimo,
        monto_maximo=v.monto_maximo,
        tasa=v.tasa,
        periodo_tasa=PeriodoTasa(v.periodo_tasa) if v.periodo_tasa else None,
        dias_gracia=v.dias_gracia,
        regla_redondeo=ReglaRedondeo(v.regla_redondeo),
    )


def _overlaps(a_desde: date, a_hasta: date | None, b_desde: date, b_hasta: date | None) -> bool:
    return (b_hasta is None or a_desde <= b_hasta) and (a_hasta is None or b_desde <= a_hasta)


# --------------------------------------------------------------------------- conceptos


async def list_conceptos(session: AsyncSession) -> list[Concepto]:
    result = await session.execute(select(Concepto).order_by(Concepto.codigo))
    return list(result.scalars())


async def get_concepto(session: AsyncSession, concepto_id: uuid.UUID) -> Concepto:
    item = await session.get(Concepto, concepto_id)
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El concepto no existe.")
    return item


async def create_concepto(
    session: AsyncSession, ctx: RequestContext, actor: User, data: ConceptoIn
) -> Concepto:
    item = Concepto(
        id=uuid.uuid4(),
        codigo=data.codigo,
        nombre=data.nombre,
        tipo=data.tipo.value,
        descripcion=data.descripcion,
        is_active=True,
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_CONCEPTO_CREATED,
        actor_user_id=actor.id,
        new_value={"codigo": item.codigo, "nombre": item.nombre, "tipo": item.tipo},
        details={"concepto_id": str(item.id)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ProblemError(HTTPStatus.CONFLICT, "Ya existe un concepto con ese código.") from exc
    return item


async def update_concepto(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    concepto_id: uuid.UUID,
    data: ConceptoUpdate,
) -> Concepto:
    item = await get_concepto(session, concepto_id)
    fields = ("nombre", "descripcion", "is_active")
    old = {f: getattr(item, f) for f in fields}
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None and field in {"nombre", "is_active"}:
            continue
        setattr(item, field, value)
    new = {f: getattr(item, f) for f in fields}
    if old != new:
        record_audit(
            session,
            ctx,
            AuditEvent.PARAMETRO_CONCEPTO_UPDATED,
            actor_user_id=actor.id,
            old_value=old,
            new_value=new,
            details={"concepto_id": str(item.id), "codigo": item.codigo},
        )
        await session.commit()
    return item


# --------------------------------------------------------------------------- vigencias


async def list_vigencias(session: AsyncSession, concepto_id: uuid.UUID) -> list[Vigencia]:
    result = await session.execute(
        select(Vigencia)
        .where(Vigencia.concepto_id == concepto_id)
        .order_by(Vigencia.fecha_desde.desc(), Vigencia.version.desc())
    )
    return list(result.unique().scalars())


async def pending_counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    result = await session.execute(
        select(Vigencia.concepto_id, func.count())
        .where(Vigencia.estado == EstadoVigencia.PENDIENTE_APROBACION)
        .group_by(Vigencia.concepto_id)
    )
    return {cid: n for cid, n in result.all()}


async def vigente_a_fecha(
    session: AsyncSession, concepto_id: uuid.UUID, fecha: date
) -> Vigencia | None:
    result = await session.execute(
        select(Vigencia).where(
            Vigencia.concepto_id == concepto_id,
            Vigencia.estado == EstadoVigencia.VIGENTE,
            Vigencia.fecha_desde <= fecha,
            or_(Vigencia.fecha_hasta.is_(None), Vigencia.fecha_hasta >= fecha),
        )
    )
    return result.unique().scalars().first()


async def vigencias_entre(
    session: AsyncSession, codigo: str, desde: date, hasta: date
) -> list[VigenciaSnapshot]:
    """Vigencias aprobadas de un concepto que rigen algún día entre `desde` y `hasta`, en orden.

    Si algún día queda sin vigencia, es un error de negocio explícito (como en `get_vigencia`).
    """
    concepto = await session.scalar(select(Concepto).where(Concepto.codigo == codigo))
    if concepto is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, f"El concepto {codigo} no existe.")
    result = await session.execute(
        select(Vigencia)
        .where(
            Vigencia.concepto_id == concepto.id,
            Vigencia.estado == EstadoVigencia.VIGENTE,
            Vigencia.fecha_desde <= hasta,
            or_(Vigencia.fecha_hasta.is_(None), Vigencia.fecha_hasta >= desde),
        )
        .order_by(Vigencia.fecha_desde)
    )
    vigencias = [snapshot(v) for v in result.unique().scalars()]
    cubierto = desde
    for v in vigencias:
        if v.fecha_desde > cubierto:
            break
        if v.fecha_hasta is None:
            return vigencias
        cubierto = max(cubierto, v.fecha_hasta + timedelta(days=1))
        if cubierto > hasta:
            return vigencias
    raise ProblemError(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        f"No hay una vigencia aprobada de {codigo} para el {cubierto.strftime('%d/%m/%Y')}.",
        type_="urn:suite-notarial:parametros:sin-vigencia",
    )


async def get_vigencia(session: AsyncSession, codigo: str, fecha: date) -> VigenciaSnapshot:
    """Parámetro vigente de un concepto a una fecha: la base de todo cálculo de boletas.

    La restricción de exclusión garantiza que haya a lo sumo una. Si no hay, es un error de
    negocio explícito: nunca se calcula con un valor supuesto.
    """
    concepto = await session.scalar(select(Concepto).where(Concepto.codigo == codigo))
    if concepto is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, f"El concepto {codigo} no existe.")
    vigencia = await vigente_a_fecha(session, concepto.id, fecha)
    if vigencia is None:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"No hay una vigencia aprobada de {codigo} para el {fecha.strftime('%d/%m/%Y')}.",
            type_="urn:suite-notarial:parametros:sin-vigencia",
        )
    return snapshot(vigencia)


def _validate_values(tipo: TipoConcepto, data: VigenciaIn) -> None:
    requeridos, prohibidos = CAMPOS_POR_TIPO[tipo]
    valores = data.model_dump()
    faltan = sorted(f for f in requeridos if valores.get(f) is None)
    sobran = sorted(f for f in prohibidos if valores.get(f) is not None)
    if faltan or sobran:
        partes = []
        if faltan:
            partes.append("faltan " + ", ".join(faltan))
        if sobran:
            partes.append("no corresponden " + ", ".join(sobran))
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"Valores incompatibles con un concepto {tipo.value}: " + "; ".join(partes) + ".",
        )


def _conflicts(
    nueva_desde: date, nueva_hasta: date | None, existentes: list[Vigencia]
) -> tuple[Vigencia | None, list[Vigencia]]:
    """Separa la vigencia abierta anterior (que se cerrará) de los solapamientos reales."""
    a_cerrar: Vigencia | None = None
    conflictos: list[Vigencia] = []
    for v in existentes:
        if not _overlaps(nueva_desde, nueva_hasta, v.fecha_desde, v.fecha_hasta):
            continue
        if (
            v.estado == EstadoVigencia.VIGENTE
            and v.fecha_hasta is None
            and v.fecha_desde < nueva_desde
        ):
            a_cerrar = v
        else:
            conflictos.append(v)
    return a_cerrar, conflictos


def _conflict_error(conflictos: list[Vigencia]) -> ProblemError:
    v = conflictos[0]
    rango = f"{v.fecha_desde.strftime('%d/%m/%Y')} al " + (
        v.fecha_hasta.strftime("%d/%m/%Y") if v.fecha_hasta else "sin fin"
    )
    estado = (
        "pendiente de aprobación" if v.estado == EstadoVigencia.PENDIENTE_APROBACION else "vigente"
    )
    return ProblemError(
        HTTPStatus.CONFLICT,
        f"Las fechas se superponen con la versión {v.version} ({estado}, {rango}).",
        extra={"vigencia_en_conflicto": str(v.id)},
    )


async def _active_for_concept(
    session: AsyncSession, concepto_id: uuid.UUID, *, lock: bool
) -> list[Vigencia]:
    stmt = select(Vigencia).where(
        Vigencia.concepto_id == concepto_id,
        Vigencia.estado.in_([EstadoVigencia.VIGENTE, EstadoVigencia.PENDIENTE_APROBACION]),
    )
    if lock:
        stmt = stmt.with_for_update(of=Vigencia)
    result = await session.execute(stmt)
    return list(result.unique().scalars())


async def proponer_vigencia(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    concepto_id: uuid.UUID,
    data: VigenciaIn,
    *,
    es_ejemplo: bool = False,
    reemplaza: Vigencia | None = None,
) -> Vigencia:
    concepto = await get_concepto(session, concepto_id)
    if not concepto.is_active:
        raise ProblemError(HTTPStatus.CONFLICT, "El concepto está inactivo.")
    _validate_values(TipoConcepto(concepto.tipo), data)
    existentes = [
        v
        for v in await _active_for_concept(session, concepto.id, lock=True)
        # La propuesta que se corrige se retira en la misma transacción: no compite.
        if reemplaza is None or v.id != reemplaza.id
    ]
    _, conflictos = _conflicts(data.fecha_desde, data.fecha_hasta, existentes)
    if conflictos:
        raise _conflict_error(conflictos)
    version = (
        await session.scalar(
            select(func.coalesce(func.max(Vigencia.version), 0)).where(
                Vigencia.concepto_id == concepto.id
            )
        )
        or 0
    ) + 1
    item = Vigencia(
        id=uuid.uuid4(),
        concepto_id=concepto.id,
        version=version,
        **data.model_dump(exclude={"regla_redondeo", "periodo_tasa"}),
        regla_redondeo=data.regla_redondeo.value,
        periodo_tasa=data.periodo_tasa.value if data.periodo_tasa else None,
        es_ejemplo=es_ejemplo,
        estado=EstadoVigencia.PENDIENTE_APROBACION.value,
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_VIGENCIA_PROPUESTA,
        actor_user_id=actor.id,
        new_value=vigencia_values(item),
        details={
            "concepto": concepto.codigo,
            "version": version,
            "vigencia_id": str(item.id),
            "motivo": data.motivo,
            **({"corrige": str(reemplaza.id)} if reemplaza else {}),
        },
    )
    await session.commit()
    await session.refresh(item, attribute_names=["concepto"])
    return item


async def _get_pending(session: AsyncSession, vigencia_id: uuid.UUID) -> Vigencia:
    result = await session.execute(
        select(Vigencia).where(Vigencia.id == vigencia_id).with_for_update(of=Vigencia)
    )
    item = result.unique().scalars().first()
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La vigencia no existe.")
    if item.estado != EstadoVigencia.PENDIENTE_APROBACION:
        raise ProblemError(HTTPStatus.CONFLICT, "La vigencia no está pendiente de aprobación.")
    return item


async def aprobar_vigencia(
    session: AsyncSession, ctx: RequestContext, actor: User, vigencia_id: uuid.UUID
) -> Vigencia:
    item = await _get_pending(session, vigencia_id)
    if item.created_by_user_id == actor.id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Quien propone una vigencia no puede aprobarla: la aprueba otra persona.",
            type_="urn:suite-notarial:parametros:cuatro-ojos",
        )
    existentes = [
        v
        for v in await _active_for_concept(session, item.concepto_id, lock=True)
        if v.id != item.id and v.estado == EstadoVigencia.VIGENTE
    ]
    a_cerrar, conflictos = _conflicts(item.fecha_desde, item.fecha_hasta, existentes)
    if conflictos:
        raise _conflict_error(conflictos)
    if a_cerrar is not None:
        a_cerrar.fecha_hasta = item.fecha_desde - timedelta(days=1)
        record_audit(
            session,
            ctx,
            AuditEvent.PARAMETRO_VIGENCIA_CERRADA,
            actor_user_id=actor.id,
            old_value={"fecha_hasta": None},
            new_value={"fecha_hasta": a_cerrar.fecha_hasta.isoformat()},
            details={
                "concepto": item.concepto.codigo,
                "vigencia_id": str(a_cerrar.id),
                "version": a_cerrar.version,
                "reemplazada_por": str(item.id),
            },
        )
        await session.flush()
    item.estado = EstadoVigencia.VIGENTE.value
    item.aprobado_por_user_id = actor.id
    item.fecha_aprobacion = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_VIGENCIA_APROBADA,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": EstadoVigencia.PENDIENTE_APROBACION.value},
        new_value={"estado": EstadoVigencia.VIGENTE.value, **vigencia_values(item)},
        details={
            "concepto": item.concepto.codigo,
            "version": item.version,
            "vigencia_id": str(item.id),
            "propuesta_por": str(item.created_by_user_id),
        },
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ProblemError(
            HTTPStatus.CONFLICT, "La vigencia se superpone con otra ya vigente."
        ) from exc
    return item


async def rechazar_vigencia(
    session: AsyncSession, ctx: RequestContext, actor: User, vigencia_id: uuid.UUID, motivo: str
) -> Vigencia:
    item = await _get_pending(session, vigencia_id)
    item.estado = EstadoVigencia.RECHAZADA.value
    item.rechazada_por_user_id = actor.id
    item.motivo_rechazo = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_VIGENCIA_RECHAZADA,
        actor_user_id=actor.id,
        old_value={"estado": EstadoVigencia.PENDIENTE_APROBACION.value},
        new_value={"estado": EstadoVigencia.RECHAZADA.value},
        details={
            "concepto": item.concepto.codigo,
            "version": item.version,
            "vigencia_id": str(item.id),
            "motivo": motivo,
        },
    )
    await session.commit()
    return item


def _retirar(
    session: AsyncSession, ctx: RequestContext, actor: User, item: Vigencia, motivo: str
) -> None:
    item.estado = EstadoVigencia.RETIRADA.value
    # Mismas columnas que el rechazo: quién la sacó de circulación y por qué.
    item.rechazada_por_user_id = actor.id
    item.motivo_rechazo = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.PARAMETRO_VIGENCIA_RETIRADA,
        actor_user_id=actor.id,
        old_value={"estado": EstadoVigencia.PENDIENTE_APROBACION.value},
        new_value={"estado": EstadoVigencia.RETIRADA.value},
        details={
            "concepto": item.concepto.codigo,
            "version": item.version,
            "vigencia_id": str(item.id),
            "motivo": motivo,
        },
    )


async def retirar_vigencia(
    session: AsyncSession, ctx: RequestContext, actor: User, vigencia_id: uuid.UUID, motivo: str
) -> Vigencia:
    """Saca de circulación una propuesta que todavía no se aprobó (nada se borra)."""
    item = await _get_pending(session, vigencia_id)
    _retirar(session, ctx, actor, item, motivo)
    await session.commit()
    return item


async def corregir_vigencia(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    vigencia_id: uuid.UUID,
    data: VigenciaIn,
) -> Vigencia:
    """Corrige una propuesta pendiente sin tocar sus valores (son inmutables): la retira y
    propone una versión nueva con los datos corregidos, todo en una sola transacción."""
    item = await _get_pending(session, vigencia_id)
    _retirar(
        session, ctx, actor, item, f"Corregida: la reemplaza una propuesta nueva. {data.motivo}"
    )
    await session.flush()
    return await proponer_vigencia(
        session, ctx, actor, item.concepto_id, data, es_ejemplo=item.es_ejemplo, reemplaza=item
    )


async def user_emails(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    result = await session.execute(select(User.id, User.email).where(User.id.in_(ids)))
    return {uid: email for uid, email in result.all()}
