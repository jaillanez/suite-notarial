"""IA asistencial: los endpoints de análisis solo crean sugerencias; los de ratificación pasan
por los servicios de DDJJ y padrón con los permisos de esas cargas (regla HIC)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.common.deps import SessionDep
from app.core.config import get_settings
from app.modules.ddjj.router import acto_out
from app.modules.ddjj.schemas import ActoIn
from app.modules.ia import lectura, service
from app.modules.ia.schemas import (
    ActoRatificadoOut,
    DescarteIn,
    EscribanoRatificadoOut,
    EstadoIaOut,
    SugerenciaOut,
)
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.padron.router import escribano_detalle
from app.modules.padron.schemas import EscribanoIn

router = APIRouter(prefix="/ia", tags=["ia"])

# Quien puede cargar actos en una DDJJ puede pedir ayuda para cargarlos.
CanOperateDDJJ = Annotated[
    Principal, Depends(require_any_permission(Perm.DDJJ_CREATE_OWN, Perm.DDJJ_APPROVE))
]
# Quien puede dar de alta escribanos puede leer un DNI para hacerlo.
CanWritePadron = Annotated[Principal, Depends(require_permissions(Perm.ESCRIBANOS_WRITE))]
CanUse = Annotated[
    Principal,
    Depends(require_any_permission(Perm.DDJJ_CREATE_OWN, Perm.DDJJ_APPROVE, Perm.ESCRIBANOS_WRITE)),
]


@router.get("/estado", response_model=EstadoIaOut)
async def estado(_: CanUse) -> EstadoIaOut:
    disponible, idiomas = lectura.estado_ocr()
    return EstadoIaOut(
        ocr_disponible=disponible, idiomas_ocr=idiomas, max_mb=get_settings().MAX_UPLOAD_MB
    )


@router.post("/minutas", response_model=SugerenciaOut, status_code=201)
async def analizar_minuta(
    principal: CanOperateDDJJ,
    session: SessionDep,
    ctx: RequestContextDep,
    ddjj_id: Annotated[uuid.UUID, Form()],
    texto: Annotated[str | None, Form(description="Texto pegado de la minuta")] = None,
    archivo: Annotated[
        UploadFile | None, File(description="PDF con texto, PNG o JPG de hasta 10 MB")
    ] = None,
) -> SugerenciaOut:
    sugerencia, resultado = await service.analizar_minuta(
        session, ctx, principal, ddjj_id, archivo=archivo, texto=texto
    )
    return SugerenciaOut.de(sugerencia, resultado)


@router.post("/dni", response_model=SugerenciaOut, status_code=201)
async def analizar_dni(
    principal: CanWritePadron,
    session: SessionDep,
    ctx: RequestContextDep,
    archivo: Annotated[UploadFile, File(description="Foto del frente o del dorso (PNG o JPG)")],
) -> SugerenciaOut:
    sugerencia, resultado = await service.analizar_dni(session, ctx, principal, archivo)
    return SugerenciaOut.de(sugerencia, resultado)


@router.get("/sugerencias/{sugerencia_id}", response_model=SugerenciaOut)
async def get_sugerencia(
    sugerencia_id: uuid.UUID, principal: CanUse, session: SessionDep
) -> SugerenciaOut:
    return SugerenciaOut.de(await service.get_sugerencia(session, principal, sugerencia_id))


@router.post("/sugerencias/{sugerencia_id}/ratificar-acto", response_model=ActoRatificadoOut)
async def ratificar_acto(
    sugerencia_id: uuid.UUID,
    body: ActoIn,
    principal: CanOperateDDJJ,
    session: SessionDep,
    ctx: RequestContextDep,
) -> ActoRatificadoOut:
    sugerencia, acto = await service.ratificar_acto(session, ctx, principal, sugerencia_id, body)
    return ActoRatificadoOut(sugerencia=SugerenciaOut.de(sugerencia), acto=acto_out(acto))


@router.post(
    "/sugerencias/{sugerencia_id}/ratificar-escribano", response_model=EscribanoRatificadoOut
)
async def ratificar_escribano(
    sugerencia_id: uuid.UUID,
    body: EscribanoIn,
    principal: CanWritePadron,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoRatificadoOut:
    sugerencia, escribano = await service.ratificar_escribano(
        session, ctx, principal, sugerencia_id, body
    )
    return EscribanoRatificadoOut(
        sugerencia=SugerenciaOut.de(sugerencia),
        escribano=await escribano_detalle(session, escribano),
    )


@router.post("/sugerencias/{sugerencia_id}/descartar", response_model=SugerenciaOut)
async def descartar(
    sugerencia_id: uuid.UUID,
    body: DescarteIn,
    principal: CanUse,
    session: SessionDep,
    ctx: RequestContextDep,
) -> SugerenciaOut:
    sugerencia = await service.descartar(session, ctx, principal, sugerencia_id, body.motivo)
    return SugerenciaOut.de(sugerencia)
