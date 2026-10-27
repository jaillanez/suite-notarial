"""Escribano a cargo de un registro: designación con fecha desde y hasta.

Cualquier escribano activo de la provincia puede quedar a cargo de cualquier registro, aunque
tenga su propio cargo en otro (lo confirmó la Caja el 27/10/2026). La designación la carga el
titular del registro desde su autogestión o el personal de la Caja. Según el ajuste
`a_cargo_requiere_aprobacion`, la del titular espera la aprobación de la Caja o rige al cargarla
(la Caja queda avisada); la que carga el personal rige siempre al cargarla.

TODO(negocio): la Caja no definió si la designación necesita su aprobación; quedan las dos
opciones y se elige en el ajuste (por defecto, aviso sin aprobación, como funciona hoy con la
clave del titular).

Solo una designación APROBADA cuenta, y solo entre sus fechas: en esos días el designado opera
las DDJJ del registro y figura en ellas como «a cargo». Nada se borra (INM): se anula o se
termina antes, con motivo, y solo si no deja actos declarados fuera de un cargo.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.ddjj.models import Acto, DeclaracionJurada
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.iam.models import User
from app.modules.padron.catalog import Cargo, EstadoDesignacion, EstadoMatricula, EstadoRegistro
from app.modules.padron.models import (
    Adscripcion,
    AjustesPadron,
    DesignacionACargo,
    Escribano,
    Persona,
    RegistroNotarial,
)
from app.modules.padron.schemas import DesignacionBaja, DesignacionIn, DesignacionTermino

FIELDS = ("registro_id", "escribano_id", "fecha_desde", "fecha_hasta", "motivo", "estado")
# Las que ocupan el registro: no puede haber dos a la vez.
ABIERTAS = (EstadoDesignacion.PENDIENTE.value, EstadoDesignacion.APROBADA.value)


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _invalid(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, message)


def _fecha(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _snapshot(item: DesignacionACargo) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in FIELDS:
        value = getattr(item, field)
        values[field] = str(value) if isinstance(value, date | uuid.UUID) else value
    return values


# --------------------------------------------------------------------------- quién puede qué


def es_personal(principal: Principal) -> bool:
    return Perm.ESCRIBANOS_WRITE.value in principal.permissions


def ve_padron(principal: Principal) -> bool:
    return Perm.ESCRIBANOS_READ.value in principal.permissions


async def _escribano_de(session: AsyncSession, user: User) -> Escribano | None:
    return await session.scalar(select(Escribano).where(Escribano.user_id == user.id))


async def registros_del_titular(session: AsyncSession, principal: Principal) -> set[uuid.UUID]:
    """Registros de los que quien consulta es titular vigente (puede designar a cargo)."""
    if Perm.DDJJ_CREATE_OWN.value not in principal.permissions:
        return set()
    escribano = await _escribano_de(session, principal.user)
    if escribano is None:
        return set()
    filas = await session.scalars(
        select(Adscripcion.registro_id).where(
            Adscripcion.escribano_id == escribano.id,
            Adscripcion.cargo == Cargo.TITULAR.value,
            Adscripcion.is_current.is_(True),
        )
    )
    return set(filas.all())


async def puede_gestionar(
    session: AsyncSession, principal: Principal, registro_id: uuid.UUID
) -> bool:
    return es_personal(principal) or registro_id in await registros_del_titular(session, principal)


async def _exigir_gestion(
    session: AsyncSession, principal: Principal, registro_id: uuid.UUID
) -> None:
    if not await puede_gestionar(session, principal, registro_id):
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Solo el titular del registro o la Caja pueden designar un escribano a cargo.",
        )


# --------------------------------------------------------------------------- ajustes


async def ajustes(session: AsyncSession) -> AjustesPadron | None:
    return await session.get(AjustesPadron, 1)


async def requiere_aprobacion(session: AsyncSession) -> bool:
    item = await ajustes(session)
    return bool(item and item.a_cargo_requiere_aprobacion)


async def fijar_ajustes(
    session: AsyncSession, ctx: RequestContext, actor: User, *, requiere: bool
) -> AjustesPadron:
    item = await session.get(AjustesPadron, 1, with_for_update=True)
    antes = bool(item and item.a_cargo_requiere_aprobacion)
    if item is None:
        item = AjustesPadron(id=1, a_cargo_requiere_aprobacion=requiere)
        session.add(item)
    item.a_cargo_requiere_aprobacion = requiere
    item.updated_by_user_id = actor.id
    item.updated_at = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_AJUSTES_CAMBIADOS,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"a_cargo_requiere_aprobacion": antes},
        new_value={"a_cargo_requiere_aprobacion": requiere},
    )
    await session.commit()
    return item


# --------------------------------------------------------------------------- vigencia


def _aprobada() -> ColumnElement[bool]:
    return DesignacionACargo.estado == EstadoDesignacion.APROBADA.value


def _cubre(desde: date, hasta: date) -> ColumnElement[bool]:
    """La designación se superpone con [desde, hasta]."""
    return and_(DesignacionACargo.fecha_desde <= hasta, DesignacionACargo.fecha_hasta >= desde)


async def aprobadas_en(
    session: AsyncSession, registro_id: uuid.UUID, desde: date, hasta: date
) -> list[DesignacionACargo]:
    """Designaciones aprobadas del registro que rigen algún día de [desde, hasta]."""
    result = await session.execute(
        select(DesignacionACargo)
        .where(DesignacionACargo.registro_id == registro_id, _aprobada(), _cubre(desde, hasta))
        .order_by(DesignacionACargo.fecha_desde)
    )
    return list(result.unique().scalars())


async def del_escribano(
    session: AsyncSession, escribano_id: uuid.UUID, *, en: date | None = None
) -> list[DesignacionACargo]:
    """Designaciones aprobadas del escribano (las que rigen en la fecha `en`, si se indica)."""
    stmt = select(DesignacionACargo).where(
        DesignacionACargo.escribano_id == escribano_id, _aprobada()
    )
    if en is not None:
        stmt = stmt.where(_cubre(en, en))
    return list((await session.execute(stmt)).unique().scalars())


@dataclass(frozen=True)
class Habilitacion:
    """Por qué un escribano puede declarar un acto en un registro en una fecha."""

    cargo: str
    designacion_id: uuid.UUID | None


async def habilitacion(
    session: AsyncSession,
    registro_id: uuid.UUID,
    escribano_id: uuid.UUID,
    fecha: date,
    *,
    excluir_designacion_id: uuid.UUID | None = None,
) -> Habilitacion | None:
    """Cargo del escribano en el registro a esa fecha: el propio o una designación a cargo."""
    cargo = await session.scalar(
        select(Adscripcion.cargo)
        .where(
            Adscripcion.registro_id == registro_id,
            Adscripcion.escribano_id == escribano_id,
            Adscripcion.fecha_desde <= fecha,
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= fecha),
        )
        .order_by(Adscripcion.fecha_desde.desc())
        .limit(1)
    )
    if cargo is not None:
        return Habilitacion(cargo, None)
    stmt = select(DesignacionACargo.id).where(
        DesignacionACargo.registro_id == registro_id,
        DesignacionACargo.escribano_id == escribano_id,
        _aprobada(),
        _cubre(fecha, fecha),
    )
    if excluir_designacion_id is not None:
        stmt = stmt.where(DesignacionACargo.id != excluir_designacion_id)
    designacion_id = await session.scalar(stmt.limit(1))
    if designacion_id is None:
        return None
    return Habilitacion(Cargo.SUPLENTE_INTERINO.value, designacion_id)


async def _actos_sin_cargo(
    session: AsyncSession, item: DesignacionACargo, desde: date, hasta: date
) -> int:
    """Actos vigentes del designado en el registro entre esas fechas que quedarían sin un cargo
    que los respalde si la designación dejara de cubrirlas."""
    fechas = await session.scalars(
        select(Acto.fecha_acto)
        .join(DeclaracionJurada, DeclaracionJurada.id == Acto.ddjj_id)
        .where(
            DeclaracionJurada.registro_id == item.registro_id,
            Acto.escribano_id == item.escribano_id,
            Acto.is_active.is_(True),
            Acto.fecha_acto >= desde,
            Acto.fecha_acto <= hasta,
        )
        .distinct()
    )
    sin_cargo = 0
    for fecha in fechas.all():
        otra = await habilitacion(
            session, item.registro_id, item.escribano_id, fecha, excluir_designacion_id=item.id
        )
        if otra is None:
            sin_cargo += 1
    return sin_cargo


# --------------------------------------------------------------------------- lectura


async def get(session: AsyncSession, designacion_id: uuid.UUID) -> DesignacionACargo:
    # populate_existing: tras crearla o resolverla, carga registro y escribano de nuevo.
    item = (
        (
            await session.execute(
                select(DesignacionACargo)
                .where(DesignacionACargo.id == designacion_id)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La designación no existe.")
    return item


async def _visibles(session: AsyncSession, principal: Principal) -> ColumnElement[bool] | None:
    """`None`: todas (personal de la Caja). Si no, las de sus registros y las propias."""
    if ve_padron(principal):
        return None
    condiciones: list[ColumnElement[bool]] = []
    registros = await registros_del_titular(session, principal)
    if registros:
        condiciones.append(DesignacionACargo.registro_id.in_(registros))
    escribano = await _escribano_de(session, principal.user)
    if escribano is not None:
        condiciones.append(DesignacionACargo.escribano_id == escribano.id)
    if not condiciones:
        return DesignacionACargo.id.is_(None)
    return or_(*condiciones)


async def exigir_lectura(
    session: AsyncSession, principal: Principal, item: DesignacionACargo
) -> None:
    condicion = await _visibles(session, principal)
    if condicion is None:
        return
    visible = await session.scalar(
        select(DesignacionACargo.id).where(DesignacionACargo.id == item.id, condicion)
    )
    if visible is None:
        # No se revela si existe una designación de un registro ajeno.
        raise ProblemError(HTTPStatus.NOT_FOUND, "La designación no existe.")


async def listar(
    session: AsyncSession,
    principal: Principal,
    page: PageParams,
    *,
    estado: EstadoDesignacion | None = None,
    registro_numero: int | None = None,
) -> tuple[list[DesignacionACargo], int]:
    stmt = select(DesignacionACargo)
    condicion = await _visibles(session, principal)
    if condicion is not None:
        stmt = stmt.where(condicion)
    if estado is not None:
        stmt = stmt.where(DesignacionACargo.estado == estado.value)
    if registro_numero is not None:
        stmt = stmt.join(
            RegistroNotarial, RegistroNotarial.id == DesignacionACargo.registro_id
        ).where(RegistroNotarial.numero_registro == registro_numero)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.execute(
        stmt.order_by(
            # Primero lo que espera una decisión; después lo más reciente.
            (DesignacionACargo.estado == EstadoDesignacion.PENDIENTE.value).desc(),
            DesignacionACargo.fecha_desde.desc(),
            DesignacionACargo.created_at.desc(),
        )
        .offset(page.offset)
        .limit(page.page_size)
    )
    return list(result.unique().scalars()), int(total or 0)


async def registros_gestionables(
    session: AsyncSession, principal: Principal
) -> list[RegistroNotarial]:
    stmt = select(RegistroNotarial).where(RegistroNotarial.estado != EstadoRegistro.CERRADO.value)
    if not es_personal(principal):
        ids = await registros_del_titular(session, principal)
        if not ids:
            return []
        stmt = stmt.where(RegistroNotarial.id.in_(ids))
    result = await session.execute(stmt.order_by(RegistroNotarial.numero_registro))
    return list(result.unique().scalars())


async def elegibles(
    session: AsyncSession, query: str, limite: int = 20
) -> list[tuple[Escribano, Adscripcion | None]]:
    """Escribanos con matrícula activa que coinciden por apellido, nombre o matrícula."""
    texto = query.strip()
    stmt = (
        select(Escribano)
        .join(Persona, Persona.id == Escribano.persona_id)
        .where(Escribano.estado_matricula == EstadoMatricula.ACTIVO.value)
    )
    if texto.isdigit():
        stmt = stmt.where(Escribano.matricula_numero == int(texto))
    else:
        patron = f"%{texto}%"
        stmt = stmt.where(
            or_(
                Persona.apellido.ilike(patron),
                Persona.nombre.ilike(patron),
                func.concat(Persona.apellido, ", ", Persona.nombre).ilike(patron),
            )
        )
    escribanos = list(
        (await session.execute(stmt.order_by(Persona.apellido, Persona.nombre).limit(limite)))
        .unique()
        .scalars()
    )
    vigentes: dict[uuid.UUID, Adscripcion] = {}
    if escribanos:
        cargos = await session.execute(
            select(Adscripcion).where(
                Adscripcion.escribano_id.in_([e.id for e in escribanos]),
                Adscripcion.is_current.is_(True),
            )
        )
        vigentes = {c.escribano_id: c for c in cargos.unique().scalars()}
    return [(e, vigentes.get(e.id)) for e in escribanos]


# --------------------------------------------------------------------------- escritura


async def designar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    data: DesignacionIn,
) -> DesignacionACargo:
    actor = principal.user
    # El bloqueo del registro serializa las designaciones: dos a la vez no se superponen.
    registro = (
        (
            await session.execute(
                select(RegistroNotarial)
                .where(RegistroNotarial.id == data.registro_id)
                .with_for_update(of=RegistroNotarial)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if registro is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El registro notarial no existe.")
    await _exigir_gestion(session, principal, registro.id)
    if registro.estado == EstadoRegistro.CERRADO.value:
        raise _conflict("El registro está cerrado.")
    escribano = await session.get(Escribano, data.escribano_id)
    if escribano is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El escribano no existe.")
    if escribano.estado_matricula != EstadoMatricula.ACTIVO.value:
        raise _conflict("Solo un escribano con matrícula ACTIVA puede quedar a cargo.")
    if data.fecha_desde < escribano.fecha_matriculacion:
        raise _invalid("La designación no puede ser anterior a la matriculación.")
    titular = await session.scalar(
        select(Adscripcion.id).where(
            Adscripcion.registro_id == registro.id,
            Adscripcion.escribano_id == escribano.id,
            Adscripcion.cargo == Cargo.TITULAR.value,
            Adscripcion.fecha_desde <= data.fecha_hasta,
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= data.fecha_desde),
        )
    )
    if titular is not None:
        raise _invalid("El titular no puede quedar a cargo de su propio registro.")
    choque = await session.scalar(
        select(DesignacionACargo)
        .where(
            DesignacionACargo.registro_id == registro.id,
            DesignacionACargo.estado.in_(ABIERTAS),
            _cubre(data.fecha_desde, data.fecha_hasta),
        )
        .limit(1)
    )
    if choque is not None:
        persona = choque.escribano.persona
        raise _conflict(
            f"El registro ya tiene a cargo a {persona.apellido}, {persona.nombre} del "
            f"{_fecha(choque.fecha_desde)} al {_fecha(choque.fecha_hasta)}"
            + (" (pendiente de aprobación)." if choque.estado != "APROBADA" else ".")
        )
    personal = es_personal(principal)
    espera = not personal and await requiere_aprobacion(session)
    ahora = datetime.now(UTC)
    item = DesignacionACargo(
        id=uuid.uuid4(),
        registro_id=registro.id,
        escribano_id=escribano.id,
        fecha_desde=data.fecha_desde,
        fecha_hasta=data.fecha_hasta,
        motivo=data.motivo,
        estado=(EstadoDesignacion.PENDIENTE if espera else EstadoDesignacion.APROBADA).value,
        created_by_user_id=actor.id,
        # La que carga la Caja queda aprobada por quien la cargó; la del titular por aviso,
        # sin aprobador.
        resuelta_por_user_id=actor.id if personal else None,
        resuelta_en=ahora if personal else None,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_A_CARGO_DESIGNADO,
        actor_user_id=actor.id,
        new_value=_snapshot(item),
        details={
            "designacion_id": str(item.id),
            "numero_registro": registro.numero_registro,
            "matricula_numero": escribano.matricula_numero,
            "cargada_por": "caja" if personal else "titular",
            "requiere_aprobacion": espera,
        },
    )
    await session.commit()
    return await get(session, item.id)


async def _para_resolver(session: AsyncSession, designacion_id: uuid.UUID) -> DesignacionACargo:
    item = (
        (
            await session.execute(
                select(DesignacionACargo)
                .where(DesignacionACargo.id == designacion_id)
                .with_for_update(of=DesignacionACargo)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La designación no existe.")
    return item


async def aprobar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, designacion_id: uuid.UUID
) -> DesignacionACargo:
    actor = principal.user
    item = await _para_resolver(session, designacion_id)
    if item.estado != EstadoDesignacion.PENDIENTE.value:
        raise _conflict("Solo se aprueba una designación pendiente.")
    if item.created_by_user_id == actor.id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN, "La aprueba otra persona, no quien cargó la designación."
        )
    if item.escribano.estado_matricula != EstadoMatricula.ACTIVO.value:
        raise _conflict("El escribano designado ya no tiene la matrícula ACTIVA.")
    antes = _snapshot(item)
    item.estado = EstadoDesignacion.APROBADA.value
    item.resuelta_por_user_id = actor.id
    item.resuelta_en = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_A_CARGO_APROBADO,
        actor_user_id=actor.id,
        old_value=antes,
        new_value=_snapshot(item),
        details={"designacion_id": str(item.id)},
    )
    await session.commit()
    return await get(session, item.id)


async def rechazar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    designacion_id: uuid.UUID,
    data: DesignacionBaja,
) -> DesignacionACargo:
    actor = principal.user
    item = await _para_resolver(session, designacion_id)
    if item.estado != EstadoDesignacion.PENDIENTE.value:
        raise _conflict("Solo se rechaza una designación pendiente.")
    antes = _snapshot(item)
    item.estado = EstadoDesignacion.RECHAZADA.value
    item.resuelta_por_user_id = actor.id
    item.resuelta_en = datetime.now(UTC)
    item.motivo_resolucion = data.motivo
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_A_CARGO_RECHAZADO,
        actor_user_id=actor.id,
        old_value=antes,
        new_value=_snapshot(item),
        details={"designacion_id": str(item.id), "motivo": data.motivo},
    )
    await session.commit()
    return await get(session, item.id)


async def anular(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    designacion_id: uuid.UUID,
    data: DesignacionBaja,
) -> DesignacionACargo:
    """Deja sin efecto una designación pendiente o aprobada que no respalda actos."""
    actor = principal.user
    item = await _para_resolver(session, designacion_id)
    await _exigir_gestion(session, principal, item.registro_id)
    if item.estado not in ABIERTAS:
        raise _conflict("La designación ya está rechazada o anulada.")
    if item.estado == EstadoDesignacion.APROBADA.value:
        actos = await _actos_sin_cargo(session, item, item.fecha_desde, item.fecha_hasta)
        if actos:
            raise _conflict(
                "El escribano a cargo ya declaró actos en esas fechas: no se puede anular. "
                "Terminala antes con la fecha del último acto."
            )
    antes = _snapshot(item)
    item.estado = EstadoDesignacion.ANULADA.value
    item.resuelta_por_user_id = actor.id
    item.resuelta_en = datetime.now(UTC)
    item.motivo_resolucion = data.motivo
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_A_CARGO_ANULADO,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value=antes,
        new_value=_snapshot(item),
        details={"designacion_id": str(item.id), "motivo": data.motivo},
    )
    await session.commit()
    return await get(session, item.id)


async def terminar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    designacion_id: uuid.UUID,
    data: DesignacionTermino,
) -> DesignacionACargo:
    """Adelanta la fecha hasta de una designación aprobada."""
    actor = principal.user
    item = await _para_resolver(session, designacion_id)
    await _exigir_gestion(session, principal, item.registro_id)
    if item.estado != EstadoDesignacion.APROBADA.value:
        raise _conflict("Solo se termina antes una designación aprobada.")
    if data.fecha_hasta < item.fecha_desde:
        raise _invalid("La nueva fecha hasta es anterior al inicio: si no llegó a regir, anulala.")
    if data.fecha_hasta >= item.fecha_hasta:
        raise _invalid(
            f"La nueva fecha hasta tiene que ser anterior al {_fecha(item.fecha_hasta)}."
        )
    actos = await _actos_sin_cargo(
        session, item, data.fecha_hasta + timedelta(days=1), item.fecha_hasta
    )
    if actos:
        raise _conflict(
            "El escribano a cargo declaró actos después de esa fecha: elegí una fecha posterior "
            "al último acto."
        )
    antes = _snapshot(item)
    item.fecha_hasta = data.fecha_hasta
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_A_CARGO_TERMINADO,
        actor_user_id=actor.id,
        old_value=antes,
        new_value=_snapshot(item),
        details={"designacion_id": str(item.id), "motivo": data.motivo},
    )
    await session.commit()
    return await get(session, item.id)
