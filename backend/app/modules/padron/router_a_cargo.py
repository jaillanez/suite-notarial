"""Escribano a cargo de un registro: /api/v1/a-cargo.

Lo usan el titular del registro (autogestión) y el personal de la Caja. La autorización fina
(¿es titular de ese registro?) se resuelve en `a_cargo`; acá solo el permiso de entrada.
"""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.common.dates import today_local
from app.common.deps import SessionDep
from app.common.pagination import Page, PageParamsDep
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.iam.models import User
from app.modules.padron import a_cargo
from app.modules.padron.catalog import EstadoDesignacion
from app.modules.padron.models import DesignacionACargo
from app.modules.padron.schemas import (
    AjustesPadronIn,
    AjustesPadronOut,
    DesignacionBaja,
    DesignacionIn,
    DesignacionOut,
    DesignacionTermino,
    EscribanoElegible,
    RegistroGestionable,
)

router = APIRouter(prefix="/a-cargo", tags=["a-cargo"])

CanUse = Annotated[
    Principal,
    Depends(require_any_permission(Perm.ESCRIBANOS_READ, Perm.DDJJ_CREATE_OWN, Perm.DDJJ_READ_OWN)),
]
CanManage = Annotated[
    Principal, Depends(require_any_permission(Perm.ESCRIBANOS_WRITE, Perm.DDJJ_CREATE_OWN))
]
CanResolve = Annotated[Principal, Depends(require_permissions(Perm.ESCRIBANOS_WRITE))]


async def designacion_out(
    session: SessionDep, principal: Principal, item: DesignacionACargo
) -> DesignacionOut:
    persona = item.escribano.persona
    personal = a_cargo.ve_padron(principal)
    gestiona = await a_cargo.puede_gestionar(session, principal, item.registro_id)
    abierta = item.estado in a_cargo.ABIERTAS
    aprobada = item.estado == EstadoDesignacion.APROBADA.value
    hoy = today_local()

    async def correo(user_id: uuid.UUID | None) -> str | None:
        if not personal or user_id is None:
            return None
        user = await session.get(User, user_id)
        return user.email if user else None

    return DesignacionOut(
        id=item.id,
        registro_id=item.registro_id,
        numero_registro=item.registro.numero_registro,
        departamento=item.registro.departamento,
        escribano_id=item.escribano_id,
        apellido_nombre=f"{persona.apellido}, {persona.nombre}",
        matricula_numero=item.escribano.matricula_numero,
        fecha_desde=item.fecha_desde,
        fecha_hasta=item.fecha_hasta,
        motivo=item.motivo,
        estado=EstadoDesignacion(item.estado),
        rige_hoy=aprobada and item.fecha_desde <= hoy <= item.fecha_hasta,
        created_at=item.created_at,
        cargada_por=await correo(item.created_by_user_id),
        resuelta_por=await correo(item.resuelta_por_user_id),
        resuelta_en=item.resuelta_en,
        motivo_resolucion=item.motivo_resolucion,
        puede_aprobar=(
            a_cargo.es_personal(principal)
            and item.estado == EstadoDesignacion.PENDIENTE.value
            and item.created_by_user_id != principal.user.id
        ),
        puede_anular=gestiona and abierta,
        puede_terminar=gestiona and aprobada and item.fecha_hasta > item.fecha_desde,
    )


@router.get("", response_model=Page[DesignacionOut])
async def listar(
    principal: CanUse,
    session: SessionDep,
    page: PageParamsDep,
    estado: EstadoDesignacion | None = None,
    registro_numero: Annotated[int | None, Query(gt=0)] = None,
) -> Page[DesignacionOut]:
    items, total = await a_cargo.listar(
        session, principal, page, estado=estado, registro_numero=registro_numero
    )
    return Page(
        items=[await designacion_out(session, principal, i) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/ajustes", response_model=AjustesPadronOut)
async def ver_ajustes(principal: CanUse, session: SessionDep) -> AjustesPadronOut:
    item = await a_cargo.ajustes(session)
    return AjustesPadronOut(
        a_cargo_requiere_aprobacion=bool(item and item.a_cargo_requiere_aprobacion),
        updated_at=item.updated_at if item else None,
        puede_editar=a_cargo.es_personal(principal),
    )


@router.put("/ajustes", response_model=AjustesPadronOut)
async def fijar_ajustes(
    body: AjustesPadronIn, principal: CanResolve, session: SessionDep, ctx: RequestContextDep
) -> AjustesPadronOut:
    item = await a_cargo.fijar_ajustes(
        session, ctx, principal.user, requiere=body.a_cargo_requiere_aprobacion
    )
    return AjustesPadronOut(
        a_cargo_requiere_aprobacion=item.a_cargo_requiere_aprobacion,
        updated_at=item.updated_at,
        puede_editar=True,
    )


@router.get("/registros", response_model=list[RegistroGestionable])
async def registros(principal: CanManage, session: SessionDep) -> list[RegistroGestionable]:
    return [
        RegistroGestionable(id=r.id, numero_registro=r.numero_registro, departamento=r.departamento)
        for r in await a_cargo.registros_gestionables(session, principal)
    ]


@router.get("/elegibles", response_model=list[EscribanoElegible])
async def elegibles(
    principal: CanManage,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=100, description="Apellido o matrícula")],
) -> list[EscribanoElegible]:
    """Solo para quien puede designar: el titular de un registro o la Caja."""
    if not a_cargo.es_personal(principal) and not await a_cargo.registros_del_titular(
        session, principal
    ):
        raise ProblemError(
            HTTPStatus.FORBIDDEN, "Solo el titular de un registro o la Caja designan a cargo."
        )
    return [
        EscribanoElegible(
            id=e.id,
            apellido_nombre=f"{e.persona.apellido}, {e.persona.nombre}",
            matricula_numero=e.matricula_numero,
            numero_registro=c.registro.numero_registro if c else None,
            departamento=c.registro.departamento if c else None,
        )
        for e, c in await a_cargo.elegibles(session, q)
    ]


@router.get("/{designacion_id}", response_model=DesignacionOut)
async def ver(designacion_id: uuid.UUID, principal: CanUse, session: SessionDep) -> DesignacionOut:
    item = await a_cargo.get(session, designacion_id)
    await a_cargo.exigir_lectura(session, principal, item)
    return await designacion_out(session, principal, item)


@router.post("", response_model=DesignacionOut, status_code=201)
async def designar(
    body: DesignacionIn, principal: CanManage, session: SessionDep, ctx: RequestContextDep
) -> DesignacionOut:
    item = await a_cargo.designar(session, ctx, principal, body)
    return await designacion_out(session, principal, item)


@router.post("/{designacion_id}/aprobar", response_model=DesignacionOut)
async def aprobar(
    designacion_id: uuid.UUID, principal: CanResolve, session: SessionDep, ctx: RequestContextDep
) -> DesignacionOut:
    item = await a_cargo.aprobar(session, ctx, principal, designacion_id)
    return await designacion_out(session, principal, item)


@router.post("/{designacion_id}/rechazar", response_model=DesignacionOut)
async def rechazar(
    designacion_id: uuid.UUID,
    body: DesignacionBaja,
    principal: CanResolve,
    session: SessionDep,
    ctx: RequestContextDep,
) -> DesignacionOut:
    item = await a_cargo.rechazar(session, ctx, principal, designacion_id, body)
    return await designacion_out(session, principal, item)


@router.post("/{designacion_id}/anular", response_model=DesignacionOut)
async def anular(
    designacion_id: uuid.UUID,
    body: DesignacionBaja,
    principal: CanManage,
    session: SessionDep,
    ctx: RequestContextDep,
) -> DesignacionOut:
    item = await a_cargo.anular(session, ctx, principal, designacion_id, body)
    return await designacion_out(session, principal, item)


@router.post("/{designacion_id}/terminar", response_model=DesignacionOut)
async def terminar(
    designacion_id: uuid.UUID,
    body: DesignacionTermino,
    principal: CanManage,
    session: SessionDep,
    ctx: RequestContextDep,
) -> DesignacionOut:
    item = await a_cargo.terminar(session, ctx, principal, designacion_id, body)
    return await designacion_out(session, principal, item)
