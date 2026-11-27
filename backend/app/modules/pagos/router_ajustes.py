"""Créditos y débitos sobre boletas: /api/v1/ajustes (Caja, 26/11/2026).

Proponen Caja y Tesorería; aprueba o rechaza el administrador, que nunca es quien propuso.
"""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select

from app.common.deps import SessionDep
from app.common.pagination import Page, PageParamsDep
from app.core.errors import ProblemError
from app.modules.ddjj.models import Boleta
from app.modules.ddjj.router import registro_resumen
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.padron.models import Escribano, RegistroNotarial
from app.modules.pagos import ajustes
from app.modules.pagos.catalog import ConceptoAjuste, EstadoAjuste, TipoAjuste
from app.modules.pagos.models import Ajuste
from app.modules.pagos.schemas import (
    AjusteIn,
    AjusteOut,
    BoletaParaAjustarOut,
    BoletaResumen,
    RechazoIn,
)
from app.modules.parametros import service as parametros

router = APIRouter(prefix="/ajustes", tags=["ajustes"])

CanProponer = Annotated[Principal, Depends(require_permissions(Perm.AJUSTES_PROPONER))]
CanAprobar = Annotated[Principal, Depends(require_permissions(Perm.AJUSTES_APROBAR))]
CanConsultar = Annotated[
    Principal,
    Depends(require_any_permission(Perm.AJUSTES_PROPONER, Perm.AJUSTES_APROBAR)),
]


async def _out(session: SessionDep, principal: Principal, items: list[Ajuste]) -> list[AjusteOut]:
    ids = {a.propuesto_por_user_id for a in items} | {
        a.resuelto_por_user_id for a in items if a.resuelto_por_user_id
    }
    emails = await parametros.user_emails(session, ids)
    numeros = dict(
        (
            await session.execute(
                select(Boleta.id, Boleta.numero).where(Boleta.id.in_({a.boleta_id for a in items}))
            )
        ).all()
    )
    aprueba = Perm.AJUSTES_APROBAR.value in principal.permissions
    return [
        AjusteOut(
            id=a.id,
            boleta_id=a.boleta_id,
            boleta_numero=numeros[a.boleta_id],
            tipo=TipoAjuste(a.tipo),
            concepto=ConceptoAjuste(a.concepto),
            importe=a.importe,
            justificacion=a.justificacion,
            resolucion=a.resolucion,
            estado=EstadoAjuste(a.estado),
            propuesto_por=emails.get(a.propuesto_por_user_id),
            propuesto_en=a.propuesto_en,
            resuelto_por=emails.get(a.resuelto_por_user_id) if a.resuelto_por_user_id else None,
            resuelto_en=a.resuelto_en,
            motivo_rechazo=a.motivo_rechazo,
            puede_resolver=(
                aprueba
                and a.estado == EstadoAjuste.PROPUESTO.value
                and a.propuesto_por_user_id != principal.user.id
            ),
        )
        for a in items
    ]


@router.get("", response_model=Page[AjusteOut])
async def listar_ajustes(
    session: SessionDep,
    principal: CanConsultar,
    page: PageParamsDep,
    estado: Annotated[EstadoAjuste | None, Query()] = None,
) -> Page[AjusteOut]:
    items, total = await ajustes.listar(session, page, estado)
    return Page(
        items=await _out(session, principal, items),
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/boleta/{numero}", response_model=BoletaParaAjustarOut)
async def boleta_para_ajustar(
    numero: Annotated[int, Path(ge=1)], session: SessionDep, principal: CanConsultar
) -> BoletaParaAjustarOut:
    """La boleta por su número, con lo que queda pagar y todos sus ajustes."""
    boleta = await session.scalar(select(Boleta).where(Boleta.numero == numero))
    if boleta is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, f"No hay una boleta N° {numero}.")
    registro = await session.get(RegistroNotarial, boleta.registro_id)
    assert registro is not None  # noqa: S101 - FK RESTRICT
    escribano = await session.get(Escribano, boleta.escribano_id) if boleta.escribano_id else None
    return BoletaParaAjustarOut(
        boleta=BoletaResumen(
            id=boleta.id,
            numero=boleta.numero,
            ddjj_id=boleta.ddjj_id,
            registro=registro_resumen(registro),
            periodo=boleta.periodo,
            estado=boleta.estado,
            fecha_pago=boleta.fecha_pago,
            total_a_pagar=boleta.total_a_pagar,
            saldo_a_pagar=await ajustes.saldo(session, boleta),
        ),
        escribano=(
            f"{escribano.persona.apellido}, {escribano.persona.nombre}" if escribano else None
        ),
        ajustes=await _out(session, principal, await ajustes.de_la_boleta(session, boleta.id)),
    )


@router.post("", response_model=AjusteOut, status_code=201)
async def proponer_ajuste(
    body: AjusteIn, session: SessionDep, principal: CanProponer, ctx: RequestContextDep
) -> AjusteOut:
    ajuste = await ajustes.proponer(
        session,
        ctx,
        principal,
        body.boleta_id,
        ajustes.Propuesta(
            tipo=body.tipo,
            concepto=body.concepto,
            importe=body.importe,
            justificacion=body.justificacion,
            resolucion=body.resolucion,
        ),
    )
    return (await _out(session, principal, [ajuste]))[0]


@router.post("/{ajuste_id}/aprobar", response_model=AjusteOut)
async def aprobar_ajuste(
    ajuste_id: uuid.UUID, session: SessionDep, principal: CanAprobar, ctx: RequestContextDep
) -> AjusteOut:
    ajuste = await ajustes.aprobar(session, ctx, principal, ajuste_id)
    return (await _out(session, principal, [ajuste]))[0]


@router.post("/{ajuste_id}/rechazar", response_model=AjusteOut)
async def rechazar_ajuste(
    ajuste_id: uuid.UUID,
    body: RechazoIn,
    session: SessionDep,
    principal: CanAprobar,
    ctx: RequestContextDep,
) -> AjusteOut:
    ajuste = await ajustes.rechazar(session, ctx, principal, ajuste_id, body.motivo)
    return (await _out(session, principal, [ajuste]))[0]
