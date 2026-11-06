"""Aportes y puntos previsionales (Ley 7231): /api/v1/previsional."""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.common.audit import AuditEvent, Severity, record_audit
from app.common.dates import today_local
from app.common.deps import SessionDep, SettingsDep
from app.common.pagination import Page, PageParamsDep
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.padron.models import Escribano
from app.modules.previsional import pdf, service
from app.modules.previsional.catalog import EstadoVinculo
from app.modules.previsional.schemas import (
    EscribanoResumen,
    EstadoCalculoOut,
    FilaPuntosOut,
    InformePuntosOut,
    OrigenOut,
    RechazarSugerenciaIn,
    SinVincularOut,
    VincularIn,
    VincularOut,
)

router = APIRouter(prefix="/previsional", tags=["previsional"])

CanReadAny = Annotated[
    Principal, Depends(require_any_permission(Perm.PUNTOS_READ_OWN, Perm.PUNTOS_READ_ALL))
]
CanReadOwn = Annotated[Principal, Depends(require_permissions(Perm.PUNTOS_READ_OWN))]
CanReadAll = Annotated[Principal, Depends(require_permissions(Perm.PUNTOS_READ_ALL))]
CanManage = Annotated[Principal, Depends(require_permissions(Perm.PUNTOS_MANAGE))]
EscribanoId = Annotated[uuid.UUID, Path(description="Escribano del padrón")]


def escribano_resumen(e: Escribano) -> EscribanoResumen:
    return EscribanoResumen(
        id=e.id,
        apellido_nombre=f"{e.persona.apellido}, {e.persona.nombre}",
        matricula_numero=e.matricula_numero,
        tipo_documento=e.persona.tipo_documento,
        numero_documento=e.persona.numero_documento,
    )


def informe_out(informe: service.Informe) -> InformePuntosOut:
    return InformePuntosOut(
        escribano=escribano_resumen(informe.escribano),
        filas=[
            FilaPuntosOut(
                anio=f.anio,
                fecha_inicio=f.fecha_inicio,
                fecha_cierre=f.fecha_cierre,
                aportes=f.aportes,
                puntos=f.puntos,
            )
            for f in informe.filas
        ],
        origenes=[
            OrigenOut(
                nombre_origen=o.nombre_origen, vinculacion=o.vinculacion, ejercicios=o.ejercicios
            )
            for o in informe.origenes
        ],
        total_aportes=informe.total_aportes,
        total_puntos=informe.total_puntos,
    )


async def _escribano_visible(
    session: SessionDep, principal: Principal, ctx: RequestContextDep, escribano_id: uuid.UUID
) -> Escribano:
    """Personal con `puntos:read_all`, o el propio escribano; cualquier otro, 403 auditado."""
    escribano = await service.get_escribano(session, escribano_id)
    if Perm.PUNTOS_READ_ALL.value in principal.permissions:
        return escribano
    if escribano.user_id == principal.user.id:
        return escribano
    record_audit(
        session,
        ctx,
        AuditEvent.PERMISSION_DENIED,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        details={"missing": [Perm.PUNTOS_READ_ALL.value], "path": ctx.path},
    )
    await session.commit()
    raise ProblemError(
        HTTPStatus.FORBIDDEN,
        "Solo podés consultar tus propios aportes y puntos.",
        type_="urn:suite-notarial:auth:forbidden",
        extra={"missing_permissions": [Perm.PUNTOS_READ_ALL.value]},
    )


async def _propio(session: SessionDep, principal: Principal) -> Escribano:
    escribano = await service.escribano_de(session, principal.user)
    if escribano is None:
        raise ProblemError(
            HTTPStatus.NOT_FOUND,
            "Tu cuenta no está vinculada a un escribano del padrón: consultá con la Caja.",
        )
    return escribano


def _pdf_response(contenido: bytes, matricula: int) -> Response:
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="informe-aportes-puntos-matricula-{matricula}.pdf"'
            ),
            "Cache-Control": "no-store",
        },
    )


PDF_RESPONSES: dict[int | str, dict[str, object]] = {200: {"content": {"application/pdf": {}}}}


@router.get("/mis-puntos", response_model=InformePuntosOut)
async def mis_puntos(principal: CanReadOwn, session: SessionDep) -> InformePuntosOut:
    """Informe de aportes y puntos del escribano que inició sesión."""
    escribano = await _propio(session, principal)
    return informe_out(await service.informe(session, escribano))


@router.get("/mis-puntos/pdf", response_class=Response, responses=PDF_RESPONSES)
async def mis_puntos_pdf(
    principal: CanReadOwn, session: SessionDep, settings: SettingsDep
) -> Response:
    escribano = await _propio(session, principal)
    informe = await service.informe(session, escribano)
    contenido = await pdf.render_pdf_async(settings, informe, today_local())
    return _pdf_response(contenido, escribano.matricula_numero)


@router.get("/escribanos/{escribano_id}/puntos", response_model=InformePuntosOut)
async def puntos_escribano(
    escribano_id: EscribanoId,
    principal: CanReadAny,
    session: SessionDep,
    ctx: RequestContextDep,
) -> InformePuntosOut:
    escribano = await _escribano_visible(session, principal, ctx, escribano_id)
    return informe_out(await service.informe(session, escribano))


@router.get(
    "/escribanos/{escribano_id}/puntos/pdf", response_class=Response, responses=PDF_RESPONSES
)
async def puntos_escribano_pdf(
    escribano_id: EscribanoId,
    principal: CanReadAny,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> Response:
    escribano = await _escribano_visible(session, principal, ctx, escribano_id)
    informe = await service.informe(session, escribano)
    contenido = await pdf.render_pdf_async(settings, informe, today_local())
    return _pdf_response(contenido, escribano.matricula_numero)


@router.get("/puntos/sin-vincular", response_model=Page[SinVincularOut])
async def sin_vincular(
    _: CanReadAll,
    session: SessionDep,
    page: PageParamsDep,
    estado: Annotated[EstadoVinculo, Query()] = EstadoVinculo.SIN_VINCULAR,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[SinVincularOut]:
    """Cola de revisión: sin escribano, con sugerencia aproximada o heredadas a confirmar."""
    items, total = await service.sin_vincular(session, estado, q, page)
    return Page(
        items=[
            SinVincularOut(
                nombre_origen=i.nombre_origen,
                estado=i.estado,
                ejercicios=i.ejercicios,
                primer_anio=i.primer_anio,
                ultimo_anio=i.ultimo_anio,
                total_aportes=i.total_aportes,
                total_puntos=i.total_puntos,
                escribano=escribano_resumen(i.escribano) if i.escribano else None,
            )
            for i in items
        ],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("/puntos/vincular", response_model=VincularOut)
async def vincular(
    body: VincularIn, principal: CanManage, session: SessionDep, ctx: RequestContextDep
) -> VincularOut:
    """Vincula (o confirma) a mano todas las filas de un nombre de la planilla. Auditado."""
    filas = await service.vincular_manual(
        session, body.nombre_origen, body.escribano_id, body.motivo, principal.user, ctx
    )
    return VincularOut(filas=filas)


@router.post("/puntos/rechazar-sugerencia", response_model=VincularOut)
async def rechazar_sugerencia(
    body: RechazarSugerenciaIn, principal: CanManage, session: SessionDep, ctx: RequestContextDep
) -> VincularOut:
    """Descarta la sugerencia aproximada de un nombre (sigue sin vincular). Auditado."""
    filas = await service.rechazar_sugerencia(
        session, body.nombre_origen, body.motivo, principal.user, ctx
    )
    return VincularOut(filas=filas)


@router.get("/calculo", response_model=EstadoCalculoOut)
async def estado_calculo(_: CanReadAll) -> EstadoCalculoOut:
    """Si la Suite puede calcular los puntos de un ejercicio nuevo (hoy no: falta la regla)."""
    estado = service.estado_calculo()
    return EstadoCalculoOut(habilitado=estado.habilitado, motivo=estado.motivo)


@router.post(
    "/ejercicios/{anio}/calcular",
    status_code=HTTPStatus.NOT_IMPLEMENTED,
    responses={501: {"description": "Falta la regla oficial de cálculo de la Caja"}},
)
async def calcular(
    anio: Annotated[int, Path(ge=1900, le=2200)], principal: CanManage, session: SessionDep
) -> None:
    """Acreditación de puntos de un ejercicio. Deshabilitada: TODO(negocio) regla oficial."""
    await service.calcular_puntos_ejercicio(session, anio, principal.user)
