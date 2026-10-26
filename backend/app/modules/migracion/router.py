"""Consulta de las corridas de migración y firma de conformidad.

La ejecución (simulacros y carga definitiva) es solo por consola: desde la web se revisa la
cuadratura y las observaciones, y Tesorería y Caja dan su conformidad sobre un simulacro.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.common.deps import SessionDep
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal, RequestContextDep, require_permissions
from app.modules.iam.models import User
from app.modules.migracion import service
from app.modules.migracion.catalog import AreaConformidad, Entidad, ModoCorrida, Severidad
from app.modules.migracion.models import Corrida
from app.modules.migracion.schemas import (
    ConformidadIn,
    ConformidadOut,
    CorridaDetalle,
    CorridaOut,
    ObservacionesPage,
    ObservacionOut,
)

router = APIRouter(prefix="/migracion", tags=["migracion"])

CanRead = Annotated[Principal, Depends(require_permissions(Perm.MIGRACION_READ))]
CanConformar = Annotated[Principal, Depends(require_permissions(Perm.MIGRACION_CONFORMAR))]


async def _nombres(session: SessionDep, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    filas = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return {user_id: nombre for user_id, nombre in filas.all()}


async def corrida_out(session: SessionDep, corrida: Corrida) -> CorridaOut:
    conformidades = await service.conformidades(session, corrida.id)
    nombres = await _nombres(
        session, {corrida.operador_user_id} | {c.user_id for c in conformidades}
    )
    return CorridaOut(
        id=corrida.id,
        modo=ModoCorrida(corrida.modo),
        estado=corrida.estado,
        huella_lote=corrida.huella_lote,
        homologacion=corrida.homologacion,
        homologacion_ejemplo=corrida.homologacion_ejemplo,
        operador=nombres.get(corrida.operador_user_id, "—"),
        created_at=corrida.created_at,
        finalizada_en=corrida.finalizada_en,
        duracion_ms=corrida.duracion_ms,
        cuadra=corrida.cuadra,
        bloqueantes=corrida.bloqueantes,
        advertencias=corrida.advertencias,
        conformidades=[
            ConformidadOut(
                area=AreaConformidad(c.area),
                firmante=nombres.get(c.user_id, "—"),
                firmada_en=c.firmada_en,
                observaciones=c.observaciones,
            )
            for c in conformidades
        ],
    )


async def corrida_detalle(session: SessionDep, corrida: Corrida) -> CorridaDetalle:
    base = await corrida_out(session, corrida)
    pendiente = await service.habilitacion_definitiva(
        session, corrida.huella_lote, corrida.homologacion_ejemplo
    )
    return CorridaDetalle(
        **base.model_dump(),
        informe=corrida.informe,
        error=corrida.error,
        pendiente_para_definitiva=pendiente,
    )


@router.get("/corridas", response_model=list[CorridaOut])
async def listar(_: CanRead, session: SessionDep) -> list[CorridaOut]:
    return [await corrida_out(session, c) for c in await service.listar(session)]


@router.get("/corridas/{corrida_id}", response_model=CorridaDetalle)
async def detalle(corrida_id: uuid.UUID, _: CanRead, session: SessionDep) -> CorridaDetalle:
    return await corrida_detalle(session, await service.get_corrida(session, corrida_id))


@router.get("/corridas/{corrida_id}/observaciones", response_model=ObservacionesPage)
async def observaciones(
    corrida_id: uuid.UUID,
    _: CanRead,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    severidad: Severidad | None = None,
    entidad: Entidad | None = None,
) -> ObservacionesPage:
    await service.get_corrida(session, corrida_id)
    filas, total = await service.observaciones(
        session,
        corrida_id,
        severidad=severidad.value if severidad else None,
        entidad=entidad.value if entidad else None,
        page=page,
        page_size=page_size,
    )
    return ObservacionesPage(
        items=[
            ObservacionOut(
                entidad=o.entidad,
                fila=o.fila,
                codigo_legado=o.codigo_legado,
                codigo=o.codigo,
                severidad=Severidad(o.severidad),
                mensaje=o.mensaje,
            )
            for o in filas
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/corridas/{corrida_id}/conformidad", response_model=CorridaDetalle)
async def conformar(
    corrida_id: uuid.UUID,
    body: ConformidadIn,
    principal: CanConformar,
    session: SessionDep,
    ctx: RequestContextDep,
) -> CorridaDetalle:
    await service.conformar(session, ctx, principal, corrida_id, body.area, body.observaciones)
    return await corrida_detalle(session, await service.get_corrida(session, corrida_id))
