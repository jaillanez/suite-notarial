"""Reglas del padrón notarial. Cada cambio se audita con valor anterior y nuevo (AUD).

Nada se borra (INM): las bajas son cambios de estado o cierres de cargo con fecha y motivo.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any

from sqlalchemy import ColumnElement, Select, String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.iam.service import revoke_all_user_sessions
from app.modules.padron import a_cargo
from app.modules.padron.catalog import (
    ESTADOS_DEFINITIVOS,
    REQUIERE_RESOLUCION,
    TRANSICIONES,
    Cargo,
    EstadoMatricula,
    EstadoRegistro,
)
from app.modules.padron.models import (
    Adscripcion,
    Circunscripcion,
    DomicilioRegistro,
    Escribano,
    HistorialEstado,
    Licencia,
    Persona,
    RegistroNotarial,
)
from app.modules.padron.schemas import (
    CargoAsignacion,
    CargoCierre,
    CargoFechaDesde,
    CircunscripcionIn,
    CircunscripcionUpdate,
    DatosACompletar,
    DomicilioCambio,
    EscribanoIn,
    EscribanoUpdate,
    EstadoCambio,
    PrimeraEscrituraDatos,
    PrimeraEscrituraIn,
    RegistroIn,
    RegistroUpdate,
)

_UNIQUE_MESSAGES = {
    "uq_padron_personas_cuit": "Ya hay una persona registrada con ese CUIT.",
    "uq_padron_escribanos_persona_id": "Esa persona ya figura como escribano.",
    "uq_padron_registros_notariales_numero_registro": "Ese número de registro ya existe.",
    "uq_padron_circunscripciones_nombre": "Ya existe una circunscripción con ese nombre.",
    "uq_padron_adscripciones_titular_vigente": "El registro ya tiene un titular vigente.",
    "uq_padron_adscripciones_cargo_vigente": "El escribano ya tiene un cargo vigente.",
    "uq_padron_registro_domicilios_vigente": "El registro ya tiene un domicilio vigente.",
    "ex_padron_registro_domicilios_sin_solapamiento": (
        "El domicilio se superpone con otro de la historia del registro."
    ),
    "ex_padron_licencias_sin_solapamiento": "La licencia se superpone con otra del escribano.",
}


def _jsonable(value: object) -> object:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _snapshot(obj: object, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: _jsonable(getattr(obj, f)) for f in fields}


async def _commit_unique(session: AsyncSession) -> None:
    """Confirma traduciendo violaciones de unicidad a 409 con un mensaje claro."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        message = _UNIQUE_MESSAGES.get(str(constraint), "El dato ya existe o entra en conflicto.")
        raise ProblemError(HTTPStatus.CONFLICT, message) from exc


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _not_found(what: str) -> ProblemError:
    return ProblemError(HTTPStatus.NOT_FOUND, f"{what} no existe.")


# --------------------------------------------------------------------------- circunscripciones

CIRC_FIELDS = ("nombre", "descripcion", "is_active")


async def list_circunscripciones(session: AsyncSession) -> list[Circunscripcion]:
    result = await session.execute(select(Circunscripcion).order_by(Circunscripcion.nombre))
    return list(result.scalars())


async def create_circunscripcion(
    session: AsyncSession, ctx: RequestContext, actor: User, data: CircunscripcionIn
) -> Circunscripcion:
    item = Circunscripcion(
        id=uuid.uuid4(),
        nombre=data.nombre,
        descripcion=data.descripcion,
        is_active=True,
        created_by_user_id=actor.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CIRCUNSCRIPCION_CREATED,
        actor_user_id=actor.id,
        new_value=_snapshot(item, CIRC_FIELDS),
        details={"circunscripcion_id": str(item.id)},
    )
    await _commit_unique(session)
    return item


async def update_circunscripcion(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    item_id: uuid.UUID,
    data: CircunscripcionUpdate,
) -> Circunscripcion:
    item = await session.get(Circunscripcion, item_id)
    if item is None:
        raise _not_found("La circunscripción")
    old = _snapshot(item, CIRC_FIELDS)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "nombre" and value is None:
            continue
        setattr(item, field, value)
    new = _snapshot(item, CIRC_FIELDS)
    if old != new:
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_CIRCUNSCRIPCION_UPDATED,
            actor_user_id=actor.id,
            old_value=old,
            new_value=new,
            details={"circunscripcion_id": str(item.id)},
        )
        await _commit_unique(session)
    return item


# --------------------------------------------------------------------------- cargos (lectura)


async def current_cargos_for_registros(
    session: AsyncSession, registro_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Adscripcion]]:
    if not registro_ids:
        return {}
    result = await session.execute(
        select(Adscripcion)
        .where(Adscripcion.registro_id.in_(registro_ids), Adscripcion.is_current.is_(True))
        .order_by(Adscripcion.cargo.desc(), Adscripcion.fecha_desde.nulls_first())
    )
    grouped: dict[uuid.UUID, list[Adscripcion]] = {rid: [] for rid in registro_ids}
    for item in result.scalars():
        grouped[item.registro_id].append(item)
    return grouped


async def current_cargo(session: AsyncSession, escribano_id: uuid.UUID) -> Adscripcion | None:
    result = await session.execute(
        select(Adscripcion).where(
            Adscripcion.escribano_id == escribano_id, Adscripcion.is_current.is_(True)
        )
    )
    return result.scalars().first()


# --------------------------------------------------------------------------- registros

REG_FIELDS = (
    "numero_registro",
    "nombre_fantasia",
    "circunscripcion_id",
    "departamento",
    "domicilio_legal",
    "telefono",
    "email",
    "fecha_creacion",
    "estado",
)


async def _active_circunscripcion(session: AsyncSession, item_id: uuid.UUID) -> Circunscripcion:
    item = await session.get(Circunscripcion, item_id)
    if item is None or not item.is_active:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "La circunscripción no existe o está inactiva."
        )
    return item


async def list_registros(
    session: AsyncSession,
    page: PageParams,
    *,
    query: str | None,
    departamento: str | None,
    estado: EstadoRegistro | None,
) -> tuple[list[RegistroNotarial], int]:
    stmt = select(RegistroNotarial)
    if query:
        q = query.strip()
        conditions: list[ColumnElement[bool]] = [
            func.lower(RegistroNotarial.nombre_fantasia).like(f"%{q.lower()}%")
        ]
        if q.isdigit():
            conditions.append(RegistroNotarial.numero_registro == int(q))
        stmt = stmt.where(or_(*conditions))
    if departamento:
        stmt = stmt.where(RegistroNotarial.departamento == departamento)
    if estado:
        stmt = stmt.where(RegistroNotarial.estado == estado.value)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.execute(
        stmt.order_by(RegistroNotarial.numero_registro).offset(page.offset).limit(page.page_size)
    )
    return list(result.unique().scalars()), total or 0


async def get_registro(session: AsyncSession, registro_id: uuid.UUID) -> RegistroNotarial:
    item = await session.get(RegistroNotarial, registro_id)
    if item is None:
        raise _not_found("El registro notarial")
    return item


async def create_registro(
    session: AsyncSession, ctx: RequestContext, actor: User, data: RegistroIn
) -> RegistroNotarial:
    await _active_circunscripcion(session, data.circunscripcion_id)
    if data.fecha_creacion is not None and data.fecha_creacion > today_local():
        # Un domicilio inicial con fecha futura dejaría sin salida el cambio de domicilio.
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La fecha de creación del registro no puede ser futura.",
        )
    item = RegistroNotarial(
        id=uuid.uuid4(),
        **data.model_dump(),
        estado=EstadoRegistro.VACANTE.value,
        created_by_user_id=actor.id,
    )
    session.add(item)
    session.add(
        DomicilioRegistro(
            registro_id=item.id,
            domicilio=item.domicilio_legal,
            fecha_desde=min(data.fecha_creacion or today_local(), today_local()),
            created_by_user_id=actor.id,
        )
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_REGISTRO_CREATED,
        actor_user_id=actor.id,
        new_value=_snapshot(item, REG_FIELDS),
        details={"registro_id": str(item.id)},
    )
    await _commit_unique(session)
    await session.refresh(item, attribute_names=["circunscripcion"])
    return item


async def update_registro(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    registro_id: uuid.UUID,
    data: RegistroUpdate,
) -> RegistroNotarial:
    item = await get_registro(session, registro_id)
    if item.estado == EstadoRegistro.CERRADO:
        raise _conflict("El registro está cerrado: no admite cambios.")
    changes = data.model_dump(exclude_unset=True)
    nuevo_domicilio = changes.pop("domicilio_legal", None)
    if nuevo_domicilio is not None and nuevo_domicilio != item.domicilio_legal:
        # El domicilio tiene historia: cambia con fecha, por «Cambiar domicilio».
        raise _conflict(
            "El domicilio se cambia con «Cambiar domicilio», indicando desde cuándo rige: así "
            "queda la historia."
        )
    if "circunscripcion_id" in changes and changes["circunscripcion_id"] is not None:
        await _active_circunscripcion(session, changes["circunscripcion_id"])
    old = _snapshot(item, REG_FIELDS)
    for field, value in changes.items():
        if value is None and field in {"circunscripcion_id", "departamento", "domicilio_legal"}:
            continue
        setattr(item, field, value)
    new = _snapshot(item, REG_FIELDS)
    if old != new:
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_REGISTRO_UPDATED,
            actor_user_id=actor.id,
            old_value=old,
            new_value=new,
            details={"registro_id": str(item.id)},
        )
        await _commit_unique(session)
        await session.refresh(item, attribute_names=["circunscripcion"])
    return item


async def close_registro(
    session: AsyncSession, ctx: RequestContext, actor: User, registro_id: uuid.UUID, motivo: str
) -> RegistroNotarial:
    item = await get_registro(session, registro_id)
    if item.estado == EstadoRegistro.CERRADO:
        raise _conflict("El registro ya está cerrado.")
    cargos = (await current_cargos_for_registros(session, [item.id]))[item.id]
    if cargos:
        raise _conflict("El registro tiene cargos vigentes: cerralos antes de cerrar el registro.")
    old_estado = item.estado
    item.estado = EstadoRegistro.CERRADO.value
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_REGISTRO_CLOSED,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": old_estado},
        new_value={"estado": item.estado},
        details={"registro_id": str(item.id), "motivo": motivo},
    )
    await session.commit()
    return item


# --------------------------------------------------------------------------- domicilios


async def list_domicilios(
    session: AsyncSession, registro_id: uuid.UUID
) -> list[tuple[DomicilioRegistro, str | None]]:
    result = await session.execute(
        select(DomicilioRegistro, User.email)
        .outerjoin(User, User.id == DomicilioRegistro.created_by_user_id)
        .where(DomicilioRegistro.registro_id == registro_id)
        .order_by(DomicilioRegistro.fecha_desde.desc())
    )
    return [(row, email) for row, email in result.all()]


async def cambiar_domicilio(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    registro_id: uuid.UUID,
    data: DomicilioCambio,
) -> RegistroNotarial:
    """Cierra el domicilio vigente el día anterior a `fecha_desde` y abre el nuevo. El registro
    conserva el vigente en `domicilio_legal` (lo leen boletas, reportes y el sitio)."""
    result = await session.execute(
        select(RegistroNotarial)
        .where(RegistroNotarial.id == registro_id)
        .with_for_update(of=RegistroNotarial)
    )
    registro = result.unique().scalars().first()
    if registro is None:
        raise _not_found("El registro notarial")
    if registro.estado == EstadoRegistro.CERRADO:
        raise _conflict("El registro está cerrado: no admite cambios.")
    if data.domicilio == registro.domicilio_legal:
        raise _conflict("Es el mismo domicilio que tiene hoy el registro.")
    if data.fecha_desde > today_local():
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "El nuevo domicilio no puede regir desde una fecha futura: cargalo cuando cambie.",
        )
    vigente = await session.scalar(
        select(DomicilioRegistro)
        .where(
            DomicilioRegistro.registro_id == registro.id, DomicilioRegistro.fecha_hasta.is_(None)
        )
        .with_for_update()
    )
    anterior: dict[str, Any] = {"domicilio": registro.domicilio_legal}
    if vigente is not None:
        if data.fecha_desde <= vigente.fecha_desde:
            raise ProblemError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"El nuevo domicilio tiene que regir después del {vigente.fecha_desde:%d/%m/%Y}, "
                "desde cuando rige el actual.",
            )
        vigente.fecha_hasta = data.fecha_desde - timedelta(days=1)
        anterior |= {
            "domicilio_id": str(vigente.id),
            "fecha_desde": vigente.fecha_desde.isoformat(),
            "fecha_hasta": vigente.fecha_hasta.isoformat(),
        }
    nuevo = DomicilioRegistro(
        id=uuid.uuid4(),
        registro_id=registro.id,
        domicilio=data.domicilio,
        fecha_desde=data.fecha_desde,
        created_by_user_id=actor.id,
    )
    session.add(nuevo)
    registro.domicilio_legal = data.domicilio
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_REGISTRO_DOMICILIO_CAMBIADO,
        actor_user_id=actor.id,
        old_value=anterior,
        new_value={
            "domicilio": data.domicilio,
            "domicilio_id": str(nuevo.id),
            "fecha_desde": data.fecha_desde.isoformat(),
        },
        details={"registro_id": str(registro.id), "numero_registro": registro.numero_registro},
    )
    await _commit_unique(session)
    await session.refresh(registro, attribute_names=["circunscripcion"])
    return registro


# --------------------------------------------------------------------------- escribanos

ESC_FIELDS = ("matricula_numero", "tomo", "folio", "fecha_matriculacion", "estado_matricula")
PRIMERA_FIELDS = (
    "primera_escritura_fecha",
    "primera_escritura_numero",
    "primera_escritura_registro",
    "primera_escritura_folio",
)
PER_FIELDS = (
    "cuit",
    "tipo_documento",
    "numero_documento",
    "apellido",
    "nombre",
    "fecha_nacimiento",
    "email",
    "telefono",
    "domicilio_real",
)


def _escribanos_query(
    query: str | None,
    estado: EstadoMatricula | None,
    registro_numero: int | None,
    departamento: str | None,
) -> Select[Escribano]:
    vigente = aliased(Adscripcion)
    registro = aliased(RegistroNotarial)
    stmt = (
        select(Escribano)
        .join(Persona, Escribano.persona_id == Persona.id)
        .outerjoin(vigente, (vigente.escribano_id == Escribano.id) & vigente.is_current.is_(True))
        .outerjoin(registro, registro.id == vigente.registro_id)
    )
    if query:
        q = query.strip()
        like = f"%{q.lower()}%"
        digits = "".join(ch for ch in q if ch.isdigit())
        conditions: list[ColumnElement[bool]] = [
            func.lower(Persona.apellido).like(like),
            func.lower(Persona.nombre).like(like),
            func.lower(Persona.apellido + ", " + Persona.nombre).like(like),
        ]
        if digits:
            conditions.append(Persona.cuit.like(f"%{digits}%"))
            conditions.append(cast(Escribano.matricula_numero, String) == digits)
            conditions.append(Persona.numero_documento == digits)
        stmt = stmt.where(or_(*conditions))
    if estado:
        stmt = stmt.where(Escribano.estado_matricula == estado.value)
    if registro_numero:
        stmt = stmt.where(registro.numero_registro == registro_numero)
    if departamento:
        stmt = stmt.where(registro.departamento == departamento)
    return stmt


async def list_escribanos(
    session: AsyncSession,
    page: PageParams,
    *,
    query: str | None,
    estado: EstadoMatricula | None,
    registro_numero: int | None,
    departamento: str | None,
) -> tuple[list[Escribano], int]:
    stmt = _escribanos_query(query, estado, registro_numero, departamento)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.execute(
        stmt.order_by(Persona.apellido, Persona.nombre, Escribano.id)
        .offset(page.offset)
        .limit(page.page_size)
    )
    return list(result.unique().scalars()), total or 0


async def current_cargos_for_escribanos(
    session: AsyncSession, escribano_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Adscripcion]:
    if not escribano_ids:
        return {}
    result = await session.execute(
        select(Adscripcion).where(
            Adscripcion.escribano_id.in_(escribano_ids), Adscripcion.is_current.is_(True)
        )
    )
    return {item.escribano_id: item for item in result.unique().scalars()}


async def get_escribano(session: AsyncSession, escribano_id: uuid.UUID) -> Escribano:
    item = await session.get(Escribano, escribano_id)
    if item is None:
        raise _not_found("El escribano")
    return item


async def create_escribano(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    data: EscribanoIn,
    *,
    escribano_id: uuid.UUID | None = None,
) -> Escribano:
    """`escribano_id` permite referenciar el alta en la misma transacción (ratificación de IA)."""
    persona = Persona(id=uuid.uuid4(), **data.persona.model_dump(), created_by_user_id=actor.id)
    persona.tipo_documento = data.persona.tipo_documento.value
    persona.email = str(data.persona.email).lower() if data.persona.email else None
    session.add(persona)
    escribano = Escribano(
        id=escribano_id or uuid.uuid4(),
        persona_id=persona.id,
        matricula_numero=data.matricula_numero,
        tomo=data.tomo,
        folio=data.folio,
        fecha_matriculacion=data.fecha_matriculacion,
        estado_matricula=EstadoMatricula.ACTIVO.value,
        created_by_user_id=actor.id,
    )
    session.add(escribano)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_ESCRIBANO_CREATED,
        actor_user_id=actor.id,
        new_value={**_snapshot(persona, PER_FIELDS), **_snapshot(escribano, ESC_FIELDS)},
        details={"escribano_id": str(escribano.id)},
    )
    await _commit_unique(session)
    await session.refresh(escribano, attribute_names=["persona"])
    return escribano


async def update_escribano(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano_id: uuid.UUID,
    data: EscribanoUpdate,
) -> Escribano:
    escribano = await get_escribano(session, escribano_id)
    persona = escribano.persona
    # Un dato «a completar» se carga una sola vez y sólo por «Completar datos» (con sus
    # controles y su auditoría propia), nunca por la edición general.
    cambios = {
        **data.model_dump(exclude_unset=True, exclude={"persona"}),
        **(data.persona.model_dump(exclude_unset=True) if data.persona is not None else {}),
    }
    duenos = {"escribano": escribano, "persona": persona}
    for campo, valor in cambios.items():
        if (
            campo in _A_COMPLETAR
            and valor is not None
            and getattr(duenos[_A_COMPLETAR[campo][0]], campo) is None
        ):
            raise _conflict(
                f"Ese dato está «a completar»: cargalo desde «Completar datos» ({campo})."
            )
    if cambios.get("fecha_matriculacion") is not None:
        await _exigir_matriculacion_antes_de_todo(
            session, escribano, cambios["fecha_matriculacion"]
        )
    old = {**_snapshot(persona, PER_FIELDS), **_snapshot(escribano, ESC_FIELDS)}
    for field, value in data.model_dump(exclude_unset=True, exclude={"persona"}).items():
        if field == "fecha_matriculacion" and value is None:
            continue
        setattr(escribano, field, value)
    if data.persona is not None:
        required = {"tipo_documento", "numero_documento", "apellido", "nombre"}
        for field, value in data.persona.model_dump(exclude_unset=True).items():
            if value is None and field in required:
                continue
            if field == "email" and value is not None:
                value = str(value).lower()
            if field == "tipo_documento" and value is not None:
                value = str(value)
            setattr(persona, field, value)
    new = {**_snapshot(persona, PER_FIELDS), **_snapshot(escribano, ESC_FIELDS)}
    if old != new:
        changed = sorted(k for k in new if old.get(k) != new[k])
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_ESCRIBANO_UPDATED,
            actor_user_id=actor.id,
            old_value={k: old[k] for k in changed},
            new_value={k: new[k] for k in changed},
            details={"escribano_id": str(escribano.id)},
        )
        await _commit_unique(session)
    return escribano


async def _exigir_matriculacion_antes_de_todo(
    session: AsyncSession, escribano: Escribano, fecha: date
) -> None:
    """El juramento no puede ser posterior a ningún cargo, designación a cargo, cambio de
    estado, licencia ni a la primera escritura ya registrados del escribano (lo usan la
    edición y «Completar datos»)."""
    from app.modules.padron.models import DesignacionACargo

    primeras: list[date | None] = [
        await session.scalar(select(func.min(columna)).where(dueno == escribano.id, *extra))
        for columna, dueno, extra in (
            (Adscripcion.fecha_desde, Adscripcion.escribano_id, ()),
            (DesignacionACargo.fecha_desde, DesignacionACargo.escribano_id, ()),
            (HistorialEstado.fecha_efectiva, HistorialEstado.escribano_id, ()),
            (Licencia.fecha_desde, Licencia.escribano_id, (Licencia.anulada.is_(False),)),
        )
    ]
    primeras.append(escribano.primera_escritura_fecha)
    primera = min((f for f in primeras if f is not None), default=None)
    if primera is not None and primera < fecha:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La fecha de juramento no puede ser posterior a su primer cargo, designación, "
            "cambio de estado, licencia o primera escritura.",
        )


# Campo a completar → (objeto que lo tiene, mensaje si ya está cargado).
_A_COMPLETAR = {
    "matricula_numero": ("escribano", "La matrícula ya está cargada"),
    "fecha_matriculacion": ("escribano", "La fecha de juramento ya está cargada"),
    "cuit": ("persona", "El CUIT ya está cargado"),
    "numero_documento": ("persona", "El número de documento ya está cargado"),
}


# La primera escritura llega a la Caja después de la afiliación: también queda «a completar».
PRIMERA_ESCRITURA = "primera_escritura"


def datos_a_completar(escribano: Escribano) -> list[str]:
    """Campos que faltan (migrados del sistema anterior sin ese dato, o la primera escritura
    que todavía no se recibió)."""
    duenos = {"escribano": escribano, "persona": escribano.persona}
    faltan = [
        campo for campo, (dueno, _) in _A_COMPLETAR.items() if getattr(duenos[dueno], campo) is None
    ]
    if escribano.primera_escritura_fecha is None:
        faltan.append(PRIMERA_ESCRITURA)
    return faltan


def antiguedad(desde: date, hoy: date) -> tuple[int, int]:
    """Años y meses calendario cumplidos entre `desde` y `hoy` (0, 0 si `desde` es futura)."""
    meses = (hoy.year - desde.year) * 12 + (hoy.month - desde.month)
    if hoy.day < desde.day:
        meses -= 1
    meses = max(meses, 0)
    return meses // 12, meses % 12


def _validar_primera_escritura(escribano: Escribano, datos: PrimeraEscrituraDatos) -> None:
    if datos.fecha > today_local():
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La fecha de la primera escritura no puede ser futura.",
        )
    juramento = escribano.fecha_matriculacion
    if juramento is not None and datos.fecha < juramento:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La primera escritura no puede ser anterior a la fecha de juramento "
            f"({juramento:%d/%m/%Y}).",
        )


def _poner_primera_escritura(
    escribano: Escribano, actor: User, datos: PrimeraEscrituraDatos
) -> None:
    escribano.primera_escritura_fecha = datos.fecha
    escribano.primera_escritura_numero = datos.numero
    escribano.primera_escritura_registro = datos.registro
    escribano.primera_escritura_folio = datos.folio
    escribano.primera_escritura_cargada_por_user_id = actor.id
    escribano.primera_escritura_cargada_en = datetime.now(UTC)


async def guardar_primera_escritura(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano_id: uuid.UUID,
    data: PrimeraEscrituraIn,
) -> Escribano:
    """Carga la primera escritura o la corrige. Corregirla exige motivo; todo queda auditado
    con el valor anterior y el nuevo."""
    escribano = await get_escribano_for_update(session, escribano_id)
    corrige = escribano.primera_escritura_fecha is not None
    if corrige and not data.motivo:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La primera escritura ya está cargada: indicá el motivo de la corrección.",
        )
    _validar_primera_escritura(escribano, data)
    old = _snapshot(escribano, PRIMERA_FIELDS)
    if old == {
        "primera_escritura_fecha": data.fecha.isoformat(),
        "primera_escritura_numero": data.numero,
        "primera_escritura_registro": data.registro,
        "primera_escritura_folio": data.folio,
    }:
        raise _conflict("La primera escritura ya tiene esos datos.")
    _poner_primera_escritura(escribano, actor, data)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_PRIMERA_ESCRITURA_CORREGIDA
        if corrige
        else AuditEvent.PADRON_PRIMERA_ESCRITURA_CARGADA,
        severity=Severity.WARNING if corrige else Severity.INFO,
        actor_user_id=actor.id,
        old_value=old,
        new_value=_snapshot(escribano, PRIMERA_FIELDS),
        details={"escribano_id": str(escribano.id), "motivo": data.motivo},
    )
    await session.commit()
    await session.refresh(escribano, attribute_names=["persona"])
    return escribano


async def completar_escribano(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano_id: uuid.UUID,
    data: DatosACompletar,
) -> Escribano:
    """Carga, una sola vez, los datos que faltaban al migrar. No cambia un dato ya cargado."""
    escribano = await get_escribano_for_update(session, escribano_id)
    persona = escribano.persona
    duenos: dict[str, Escribano | Persona] = {"escribano": escribano, "persona": persona}
    cambios = data.model_dump(exclude_none=True, exclude={"primera_escritura"})
    primera = data.primera_escritura
    if primera is not None and escribano.primera_escritura_fecha is not None:
        raise _conflict(
            "La primera escritura ya está cargada: se corrige desde «Primera escritura», con "
            "motivo."
        )
    for campo in cambios:
        dueno, mensaje = _A_COMPLETAR[campo]
        if getattr(duenos[dueno], campo) is not None:
            raise _conflict(f"{mensaje}: no se cambia desde «a completar».")
    fecha = cambios.get("fecha_matriculacion")
    if fecha is not None:
        await _exigir_matriculacion_antes_de_todo(session, escribano, fecha)
    old: dict[str, Any] = {campo: None for campo in cambios}
    for campo, valor in cambios.items():
        setattr(duenos[_A_COMPLETAR[campo][0]], campo, valor)
    nuevos: dict[str, Any] = {campo: _jsonable(valor) for campo, valor in cambios.items()}
    if primera is not None:
        # Se valida después de cargar el juramento que pueda venir en el mismo envío.
        _validar_primera_escritura(escribano, primera)
        old |= _snapshot(escribano, PRIMERA_FIELDS)
        _poner_primera_escritura(escribano, actor, primera)
        nuevos |= _snapshot(escribano, PRIMERA_FIELDS)
    campos = sorted(cambios) + ([PRIMERA_ESCRITURA] if primera is not None else [])
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_ESCRIBANO_COMPLETADO,
        actor_user_id=actor.id,
        old_value=old,
        new_value=nuevos,
        details={"escribano_id": str(escribano.id), "campos": campos},
    )
    await _commit_unique(session)
    await session.refresh(escribano, attribute_names=["persona"])
    return escribano


async def change_estado(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano_id: uuid.UUID,
    data: EstadoCambio,
) -> Escribano:
    escribano = await get_escribano(session, escribano_id)
    actual = EstadoMatricula(escribano.estado_matricula)
    nuevo = data.nuevo_estado
    if actual == nuevo:
        raise _conflict(f"La matrícula ya está en estado {nuevo.value}.")
    permitidos = TRANSICIONES[actual]
    if nuevo not in permitidos:
        opciones = ", ".join(sorted(e.value for e in permitidos)) or "ninguno"
        raise _conflict(
            f"No se puede pasar de {actual.value} a {nuevo.value}. Estados posibles: {opciones}."
        )
    if (actual, nuevo) in REQUIERE_RESOLUCION and not data.resolucion_respaldo:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La reincorporación requiere citar la resolución que la dispone.",
        )
    if escribano.fecha_matriculacion is None:
        raise _conflict(
            "Falta la fecha de juramento: completala desde «Completar datos» antes de "
            "esta operación."
        )
    if data.fecha_efectiva < escribano.fecha_matriculacion:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La fecha efectiva no puede ser anterior al juramento.",
        )
    if nuevo in ESTADOS_DEFINITIVOS:
        vigente = await current_cargo(session, escribano.id)
        if vigente is not None:
            raise _conflict(
                f"Tiene un cargo vigente en el Registro {vigente.registro.numero_registro}: "
                "cerralo antes de pasar a un estado definitivo."
            )
    session.add(
        HistorialEstado(
            escribano_id=escribano.id,
            estado_anterior=actual.value,
            estado_nuevo=nuevo.value,
            motivo=data.motivo,
            resolucion_respaldo=data.resolucion_respaldo,
            fecha_efectiva=data.fecha_efectiva,
            operador_user_id=actor.id,
        )
    )
    escribano.estado_matricula = nuevo.value
    escribano.motivo_ultimo_cambio_estado = data.motivo
    escribano.fecha_ultimo_cambio_estado = datetime.now(UTC)
    if nuevo in ESTADOS_DEFINITIVOS:
        await _suspend_linked_account(session, ctx, actor, escribano, nuevo, data.motivo)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_ESTADO_CHANGED,
        severity=Severity.WARNING if nuevo != EstadoMatricula.ACTIVO else Severity.INFO,
        actor_user_id=actor.id,
        old_value={"estado_matricula": actual.value},
        new_value={"estado_matricula": nuevo.value},
        details={
            "escribano_id": str(escribano.id),
            "matricula_numero": escribano.matricula_numero,
            "motivo": data.motivo,
            "resolucion_respaldo": data.resolucion_respaldo,
            "fecha_efectiva": data.fecha_efectiva.isoformat(),
        },
    )
    await session.commit()
    return escribano


async def _suspend_linked_account(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano: Escribano,
    nuevo: EstadoMatricula,
    motivo: str,
) -> None:
    """Una baja definitiva de la matrícula suspende la cuenta de autogestión en la misma
    transacción. Volver a ACTIVO no la reactiva: lo decide un administrador de usuarios.
    La SUSPENSIÓN no toca la cuenta: la deja en solo consulta (ver iam.deps).
    """
    if escribano.user_id is None:
        return
    user = await session.get(User, escribano.user_id)
    if user is None or not user.is_active:
        return
    if user.id == actor.id:
        raise _conflict("No podés dar de baja tu propia matrícula: tu cuenta quedaría suspendida.")
    # Una cuenta solo de autogestión se suspende como consecuencia directa de la baja. Si tiene
    # otros roles, suspenderla es una decisión de administración de usuarios.
    solo_autogestion = set(user.role_codes) <= {"ROLE_ESCRIBANO"}
    if not solo_autogestion and Perm.USERS_SUSPEND.value not in actor.permission_codes:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "La cuenta vinculada tiene otros roles: suspenderla requiere el permiso users:suspend.",
            type_="urn:suite-notarial:auth:forbidden",
            extra={"missing_permissions": [Perm.USERS_SUSPEND.value]},
        )
    old = {"is_active": True, "suspension_reason": user.suspension_reason}
    user.is_active = False
    user.suspension_reason = f"Matrícula {nuevo.value}: {motivo}"[:500]
    user.suspended_at = datetime.now(UTC)
    user.suspended_by_user_id = actor.id
    await revoke_all_user_sessions(session, user.id, "matricula_baja")
    record_audit(
        session,
        ctx,
        AuditEvent.USER_STATUS_CHANGED,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        target_user_id=user.id,
        old_value=old,
        new_value={"is_active": False, "suspension_reason": user.suspension_reason},
        details={"origen": "padron", "escribano_id": str(escribano.id)},
    )


async def get_escribano_for_update(session: AsyncSession, escribano_id: uuid.UUID) -> Escribano:
    result = await session.execute(
        select(Escribano).where(Escribano.id == escribano_id).with_for_update(of=Escribano)
    )
    item = result.unique().scalars().first()
    if item is None:
        raise _not_found("El escribano")
    return item


async def list_historial(
    session: AsyncSession, escribano_id: uuid.UUID
) -> list[tuple[HistorialEstado, str | None]]:
    result = await session.execute(
        select(HistorialEstado, User.email)
        .outerjoin(User, User.id == HistorialEstado.operador_user_id)
        .where(HistorialEstado.escribano_id == escribano_id)
        .order_by(HistorialEstado.fecha_cambio.desc())
    )
    return [(row, email) for row, email in result.all()]


async def list_cargos(session: AsyncSession, escribano_id: uuid.UUID) -> list[Adscripcion]:
    result = await session.execute(
        select(Adscripcion)
        .where(Adscripcion.escribano_id == escribano_id)
        .order_by(Adscripcion.fecha_desde.desc().nulls_last(), Adscripcion.created_at.desc())
    )
    return list(result.unique().scalars())


# --------------------------------------------------------------------------- cargos (escritura)

CARGO_FIELDS = ("registro_id", "cargo", "fecha_desde", "fecha_hasta", "is_current")


async def assign_cargo(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano_id: uuid.UUID,
    data: CargoAsignacion,
) -> Adscripcion:
    if data.cargo == Cargo.SUPLENTE_INTERINO:
        # Quien queda a cargo conserva su propio cargo: va como designación con fechas.
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "El escribano a cargo se registra como designación, con fecha desde y hasta "
            "(Escribano a cargo).",
        )
    escribano = await get_escribano(session, escribano_id)
    if escribano.estado_matricula != EstadoMatricula.ACTIVO:
        raise _conflict("Solo un escribano con matrícula ACTIVA puede asumir un cargo.")
    if escribano.fecha_matriculacion is None:
        raise _conflict(
            "Falta la fecha de juramento: completala desde «Completar datos» antes de "
            "esta operación."
        )
    if data.fecha_desde < escribano.fecha_matriculacion:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La designación no puede ser anterior al juramento.",
        )
    registro = await get_registro(session, data.registro_id)
    if registro.estado == EstadoRegistro.CERRADO:
        raise _conflict("El registro está cerrado.")
    vigente = await current_cargo(session, escribano.id)
    if vigente is not None:
        raise _conflict(
            f"Ya tiene un cargo vigente en el Registro {vigente.registro.numero_registro}: "
            "cerralo antes de asignar otro."
        )
    if data.cargo == Cargo.TITULAR:
        cargos = (await current_cargos_for_registros(session, [registro.id]))[registro.id]
        if any(c.cargo == Cargo.TITULAR for c in cargos):
            raise _conflict("El registro ya tiene un titular vigente.")
    item = Adscripcion(
        id=uuid.uuid4(),
        escribano_id=escribano.id,
        registro_id=registro.id,
        cargo=data.cargo.value,
        resolucion_designacion=data.resolucion_designacion,
        fecha_desde=data.fecha_desde,
        is_current=True,
        created_by_user_id=actor.id,
    )
    session.add(item)
    old_estado = registro.estado
    if data.cargo == Cargo.TITULAR:
        registro.estado = EstadoRegistro.ACTIVO.value
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CARGO_ASSIGNED,
        actor_user_id=actor.id,
        new_value=_snapshot(item, CARGO_FIELDS),
        details={
            "escribano_id": str(escribano.id),
            "matricula_numero": escribano.matricula_numero,
            "numero_registro": registro.numero_registro,
            "registro_estado": {"antes": old_estado, "despues": registro.estado},
        },
    )
    await _commit_unique(session)
    await session.refresh(item, attribute_names=["registro"])
    return item


async def close_cargo(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    cargo_id: uuid.UUID,
    data: CargoCierre,
) -> Adscripcion:
    item = await session.get(Adscripcion, cargo_id)
    if item is None:
        raise _not_found("El cargo")
    if not item.is_current:
        raise _conflict("El cargo ya está cerrado.")
    if data.fecha_hasta < item.inicio:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "La fecha de cierre es anterior a la designación."
        )
    old = _snapshot(item, CARGO_FIELDS)
    item.fecha_hasta = data.fecha_hasta
    item.is_current = False
    item.motivo_cierre = data.motivo
    registro = item.registro
    old_estado = registro.estado
    if item.cargo == Cargo.TITULAR and registro.estado == EstadoRegistro.ACTIVO:
        registro.estado = EstadoRegistro.VACANTE.value
    if item.cargo == Cargo.TITULAR:
        await a_cargo.cerrar_por_cierre_de_titular(session, ctx, actor, item)
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CARGO_CLOSED,
        actor_user_id=actor.id,
        old_value=old,
        new_value=_snapshot(item, CARGO_FIELDS),
        details={
            "cargo_id": str(item.id),
            "escribano_id": str(item.escribano_id),
            "numero_registro": registro.numero_registro,
            "motivo": data.motivo,
            "registro_estado": {"antes": old_estado, "despues": registro.estado},
        },
    )
    await session.commit()
    return item


async def completar_fecha_desde(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    cargo_id: uuid.UUID,
    data: CargoFechaDesde,
) -> Adscripcion:
    """Carga la fecha desde de un cargo migrado sin ella («a completar»). Una vez cargada no se
    cambia por acá."""
    item = (
        (
            await session.execute(
                select(Adscripcion)
                .where(Adscripcion.id == cargo_id)
                .with_for_update(of=Adscripcion)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if item is None:
        raise _not_found("El cargo")
    if item.fecha_desde is not None:
        raise _conflict("El cargo ya tiene fecha desde: no está «a completar».")
    fecha = data.fecha_desde
    if fecha > today_local():
        raise ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, "La fecha desde no puede ser futura.")
    if item.fecha_hasta is not None and fecha > item.fecha_hasta:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"La fecha desde no puede ser posterior al cierre del cargo "
            f"({item.fecha_hasta:%d/%m/%Y}).",
        )
    juramento = item.escribano.fecha_matriculacion
    if juramento is not None and fecha < juramento:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "La designación no puede ser anterior al juramento."
        )
    # No puede pisar otro cargo propio con fechas (uno que también esté «a completar» se
    # controla cuando se le cargue la suya).
    choque = await session.scalar(
        select(Adscripcion)
        .where(
            Adscripcion.escribano_id == item.escribano_id,
            Adscripcion.id != item.id,
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= fecha),
            Adscripcion.fecha_desde <= (item.fecha_hasta or date.max),
        )
        .limit(1)
    )
    if choque is not None:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"Se superpone con su cargo en el Registro {choque.registro.numero_registro}.",
        )
    old = _snapshot(item, CARGO_FIELDS)
    item.fecha_desde = fecha
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CARGO_COMPLETADO,
        actor_user_id=actor.id,
        old_value=old,
        new_value=_snapshot(item, CARGO_FIELDS),
        details={
            "cargo_id": str(item.id),
            "escribano_id": str(item.escribano_id),
            "numero_registro": item.registro.numero_registro,
        },
    )
    await session.commit()
    return item


async def link_account(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano: Escribano,
    user: User,
) -> None:
    """Vincula la cuenta recién creada. El llamador confirma todo en una sola transacción."""
    escribano.user_id = user.id
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CUENTA_CREATED,
        actor_user_id=actor.id,
        target_user_id=user.id,
        details={
            "escribano_id": str(escribano.id),
            "matricula_numero": escribano.matricula_numero,
            "email": user.email,
        },
    )
