"""Endpoints del motor paramétrico: /api/v1/parametros."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.common.dates import today_local
from app.common.deps import SessionDep
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal, RequestContextDep, require_permissions
from app.modules.parametros import motor, service
from app.modules.parametros.catalog import EstadoVigencia, ReglaRedondeo, TipoConcepto
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.parametros.schemas import (
    ConceptoIn,
    ConceptoOut,
    ConceptoUpdate,
    Rechazo,
    SimulacionIn,
    SimulacionOut,
    VigenciaIn,
    VigenciaOut,
)

router = APIRouter(prefix="/parametros", tags=["parametros"])

CanRead = Annotated[Principal, Depends(require_permissions(Perm.PARAMETERS_READ))]
CanWrite = Annotated[Principal, Depends(require_permissions(Perm.PARAMETERS_WRITE))]
CanApprove = Annotated[Principal, Depends(require_permissions(Perm.PARAMETERS_APPROVE))]


def vigencia_out(v: Vigencia, emails: dict[uuid.UUID, str]) -> VigenciaOut:
    return VigenciaOut(
        id=v.id,
        concepto_id=v.concepto_id,
        concepto_codigo=v.concepto.codigo,
        version=v.version,
        fecha_desde=v.fecha_desde,
        fecha_hasta=v.fecha_hasta,
        porcentaje=v.porcentaje,
        monto_fijo=v.monto_fijo,
        monto_minimo=v.monto_minimo,
        monto_maximo=v.monto_maximo,
        tasa_mensual=v.tasa_mensual,
        dias_gracia=v.dias_gracia,
        regla_redondeo=ReglaRedondeo(v.regla_redondeo),
        es_ejemplo=v.es_ejemplo,
        estado=EstadoVigencia(v.estado),
        resolucion_respaldo=v.resolucion_respaldo,
        motivo=v.motivo,
        created_at=v.created_at,
        creado_por=emails.get(v.created_by_user_id),
        aprobado_por=emails.get(v.aprobado_por_user_id) if v.aprobado_por_user_id else None,
        fecha_aprobacion=v.fecha_aprobacion,
        motivo_rechazo=v.motivo_rechazo,
    )


async def _emails_for(session: SessionDep, items: list[Vigencia]) -> dict[uuid.UUID, str]:
    ids = {v.created_by_user_id for v in items} | {
        v.aprobado_por_user_id for v in items if v.aprobado_por_user_id
    }
    return await service.user_emails(session, ids)


async def concepto_out(
    session: SessionDep, c: Concepto, fecha: date, pendientes: dict[uuid.UUID, int]
) -> ConceptoOut:
    vigente = await service.vigente_a_fecha(session, c.id, fecha)
    emails = await _emails_for(session, [vigente] if vigente else [])
    return ConceptoOut(
        id=c.id,
        codigo=c.codigo,
        nombre=c.nombre,
        tipo=TipoConcepto(c.tipo),
        descripcion=c.descripcion,
        is_active=c.is_active,
        vigente=vigencia_out(vigente, emails) if vigente else None,
        pendientes=pendientes.get(c.id, 0),
    )


@router.get("/conceptos", response_model=list[ConceptoOut])
async def list_conceptos(
    _: CanRead,
    session: SessionDep,
    fecha: Annotated[date | None, Query(description="Fecha de consulta; por defecto hoy")] = None,
) -> list[ConceptoOut]:
    """Catálogo con el valor vigente de cada concepto a la fecha indicada."""
    when = fecha or today_local()
    pendientes = await service.pending_counts(session)
    return [
        await concepto_out(session, c, when, pendientes)
        for c in await service.list_conceptos(session)
    ]


@router.post("/conceptos", response_model=ConceptoOut, status_code=201)
async def create_concepto(
    body: ConceptoIn, principal: CanWrite, session: SessionDep, ctx: RequestContextDep
) -> ConceptoOut:
    item = await service.create_concepto(session, ctx, principal.user, body)
    return await concepto_out(session, item, today_local(), {})


@router.patch("/conceptos/{concepto_id}", response_model=ConceptoOut)
async def update_concepto(
    concepto_id: uuid.UUID,
    body: ConceptoUpdate,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> ConceptoOut:
    item = await service.update_concepto(session, ctx, principal.user, concepto_id, body)
    pendientes = await service.pending_counts(session)
    return await concepto_out(session, item, today_local(), pendientes)


@router.get("/conceptos/{concepto_id}/vigencias", response_model=list[VigenciaOut])
async def list_vigencias(
    concepto_id: uuid.UUID, _: CanRead, session: SessionDep
) -> list[VigenciaOut]:
    await service.get_concepto(session, concepto_id)
    items = await service.list_vigencias(session, concepto_id)
    emails = await _emails_for(session, items)
    return [vigencia_out(v, emails) for v in items]


@router.post("/conceptos/{concepto_id}/vigencias", response_model=VigenciaOut, status_code=201)
async def proponer_vigencia(
    concepto_id: uuid.UUID,
    body: VigenciaIn,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> VigenciaOut:
    item = await service.proponer_vigencia(session, ctx, principal.user, concepto_id, body)
    return vigencia_out(item, await _emails_for(session, [item]))


@router.post("/vigencias/{vigencia_id}/aprobar", response_model=VigenciaOut)
async def aprobar_vigencia(
    vigencia_id: uuid.UUID, principal: CanApprove, session: SessionDep, ctx: RequestContextDep
) -> VigenciaOut:
    item = await service.aprobar_vigencia(session, ctx, principal.user, vigencia_id)
    return vigencia_out(item, await _emails_for(session, [item]))


@router.post("/vigencias/{vigencia_id}/rechazar", response_model=VigenciaOut)
async def rechazar_vigencia(
    vigencia_id: uuid.UUID,
    body: Rechazo,
    principal: CanApprove,
    session: SessionDep,
    ctx: RequestContextDep,
) -> VigenciaOut:
    item = await service.rechazar_vigencia(session, ctx, principal.user, vigencia_id, body.motivo)
    return vigencia_out(item, await _emails_for(session, [item]))


@router.post("/simulacion", response_model=SimulacionOut)
async def simular(body: SimulacionIn, _: CanRead, session: SessionDep) -> SimulacionOut:
    """Calcula con la vigencia aplicable a la fecha, sin guardar nada."""
    snap = await service.get_vigencia(session, body.concepto_codigo, body.fecha)
    vigencia = await session.get(Vigencia, snap.vigencia_id)
    assert vigencia is not None  # noqa: S101 (recién resuelta)
    out = vigencia_out(vigencia, await _emails_for(session, [vigencia]))
    try:
        if snap.tipo == TipoConcepto.PORCENTUAL_ACTO:
            if body.base_imponible is None:
                raise motor.MotorError("Indicá la base imponible.")
            resultado = motor.aporte_porcentual(body.base_imponible, snap)
            return SimulacionOut(
                vigencia=out,
                resultado=resultado,
                detalle=f"{snap.porcentaje} % sobre {body.base_imponible}, con mínimo y tope.",
            )
        if snap.tipo == TipoConcepto.FIJO_MENSUAL:
            return SimulacionOut(
                vigencia=out, resultado=motor.aporte_fijo(snap), detalle="Monto fijo mensual."
            )
        if body.monto is None or body.vencimiento is None or body.fecha_pago is None:
            raise motor.MotorError("Indicá monto, vencimiento y fecha de pago.")
        dias = motor.dias_de_mora(body.vencimiento, body.fecha_pago, snap)
        return SimulacionOut(
            vigencia=out,
            resultado=motor.interes_mora(body.monto, dias, snap),
            dias_mora=dias,
            detalle=f"{snap.tasa_mensual} % mensual, {dias} días computables.",
        )
    except motor.MotorError as exc:
        raise ProblemError(422, str(exc)) from exc
