"""Endpoints de DDJJ y boletas: /api/v1/ddjj y la verificación pública de boletas."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.common.dates import today_local
from app.common.deps import SessionDep, SettingsDep
from app.common.pagination import Page, PageParamsDep
from app.modules.ddjj import pdf, protocolo, service
from app.modules.ddjj.catalog import (
    CategoriaActo,
    EstadoBoleta,
    EstadoDDJJ,
    MotivoExencion,
    TipoProtocolo,
)
from app.modules.ddjj.models import Acto, Boleta, DeclaracionJurada, Vencimiento
from app.modules.ddjj.schemas import (
    ActoIn,
    ActoOut,
    AporteActoOut,
    BajaActo,
    BoletaOut,
    ComprobanteResumen,
    ControlOut,
    DeclaracionDetalle,
    DeclaracionIn,
    DeclaracionOut,
    EmitirBoletaIn,
    EscribanoResumen,
    HuecoOut,
    LiquidacionOut,
    Periodo,
    PresentarIn,
    RegistroOperable,
    RegistroResumen,
    TramoMoraOut,
    TramoOut,
    VencimientoIn,
    VencimientoOut,
    VerificacionActoIn,
    VerificacionActoOut,
    VerificacionOut,
)
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.padron.catalog import Cargo
from app.modules.padron.models import RegistroNotarial
from app.modules.pagos import service as pagos_service
from app.modules.pagos.catalog import EstadoComprobante
from app.modules.pagos.models import Comprobante
from app.modules.parametros import service as parametros
from app.modules.parametros.catalog import PeriodoTasa

router = APIRouter(prefix="/ddjj", tags=["ddjj"])
public_router = APIRouter(prefix="/boletas", tags=["boletas"])

CanRead = Annotated[
    Principal,
    Depends(require_any_permission(Perm.DDJJ_READ_OWN, Perm.DDJJ_READ_ALL, Perm.DDJJ_APPROVE)),
]
CanOperate = Annotated[
    Principal, Depends(require_any_permission(Perm.DDJJ_CREATE_OWN, Perm.DDJJ_APPROVE))
]
CanReadBoletas = Annotated[
    Principal, Depends(require_any_permission(Perm.BOLETAS_READ_OWN, Perm.BOLETAS_READ_ALL))
]
CanSetCalendar = Annotated[Principal, Depends(require_permissions(Perm.PARAMETERS_WRITE))]


# --------------------------------------------------------------------------- serialización


def registro_resumen(r: RegistroNotarial) -> RegistroResumen:
    return RegistroResumen(
        id=r.id,
        numero_registro=r.numero_registro,
        nombre_fantasia=r.nombre_fantasia,
        departamento=r.departamento,
    )


def escribano_resumen(c: service.CargoEnPeriodo) -> EscribanoResumen:
    persona = c.escribano.persona
    return EscribanoResumen(
        id=c.escribano_id,
        apellido_nombre=f"{persona.apellido}, {persona.nombre}",
        matricula_numero=c.escribano.matricula_numero,
        cargo=Cargo(c.cargo),
    )


def _unicos(cargos: list[service.CargoEnPeriodo]) -> list[EscribanoResumen]:
    vistos: set[uuid.UUID] = set()
    out = []
    for c in cargos:
        if c.escribano_id not in vistos:
            vistos.add(c.escribano_id)
            out.append(escribano_resumen(c))
    return out


def acto_out(a: Acto) -> ActoOut:
    persona = a.escribano.persona
    return ActoOut(
        id=a.id,
        escribano_id=a.escribano_id,
        escribano=f"{persona.apellido}, {persona.nombre}",
        matricula_numero=a.escribano.matricula_numero,
        cargo=Cargo(a.cargo),
        tipo_protocolo=TipoProtocolo(a.tipo_protocolo),
        numero_escritura=a.numero_escritura,
        orden_en_escritura=a.orden_en_escritura,
        folio=a.folio,
        fecha_acto=a.fecha_acto,
        naturaleza=a.naturaleza,
        categoria=CategoriaActo(a.categoria),
        base_imponible=a.base_imponible,
        motivo_exencion=MotivoExencion(a.motivo_exencion) if a.motivo_exencion else None,
        detalle_exencion=a.detalle_exencion,
        aporte=a.aporte,
        vigencia_id=a.vigencia_id,
    )


CAJA = "Caja Notarial"


async def _actor(
    session: SessionDep, principal: Principal, user_id: uuid.UUID | None
) -> str | None:
    """Correo de quien operó. A un escribano no se le muestran los correos del personal."""
    if user_id is None:
        return None
    if user_id != principal.user.id and not service.ve_todo(principal):
        return CAJA
    return (await parametros.user_emails(session, {user_id})).get(user_id)


def _comprobante_resumen(c: Comprobante | None) -> ComprobanteResumen | None:
    if c is None:
        return None
    return ComprobanteResumen(
        id=c.id,
        estado=EstadoComprobante(c.estado),
        importe_declarado=c.importe_declarado,
        motivo_rechazo=c.motivo_rechazo,
        created_at=c.created_at,
    )


async def boleta_out(session: SessionDep, principal: Principal, b: Boleta) -> BoletaOut:
    registro = await session.get(RegistroNotarial, b.registro_id)
    ddjj = await session.get(DeclaracionJurada, b.ddjj_id)
    assert registro is not None and ddjj is not None  # noqa: S101 - FK RESTRICT
    return BoletaOut(
        id=b.id,
        numero=b.numero,
        codigo_verificacion=b.codigo_verificacion,
        ddjj_id=b.ddjj_id,
        registro=registro_resumen(registro),
        periodo=b.periodo,
        numero_rectificativa=ddjj.numero_rectificativa,
        estado=EstadoBoleta(b.estado),
        fecha_emision=b.fecha_emision,
        fecha_vencimiento=b.fecha_vencimiento,
        fecha_pago=b.fecha_pago,
        dias_mora=b.dias_mora,
        total_protocolos=b.total_protocolos,
        aporte_minimo=b.aporte_minimo,
        excedente=b.excedente,
        aporte_medico=b.aporte_medico,
        cantidad_aportes_medicos=b.cantidad_aportes_medicos,
        total_en_termino=b.total_en_termino,
        interes_mora=b.interes_mora,
        tramos_mora=[
            TramoMoraOut(
                desde=t.desde,
                hasta=t.hasta,
                dias=t.dias,
                tasa=t.tasa,
                periodo_tasa=PeriodoTasa(t.periodo_tasa),
                interes=t.interes,
            )
            for t in b.tramos_mora
        ],
        total_a_pagar=b.total_a_pagar,
        created_at=b.created_at,
        emitida_por=await _actor(session, principal, b.emitida_por_user_id),
        anulada_en=b.anulada_en,
        motivo_anulacion=b.motivo_anulacion,
        comprobante=_comprobante_resumen(
            (await pagos_service.ultimos_por_boleta(session, [b.id])).get(b.id)
        ),
    )


async def declaracion_out(
    session: SessionDep, principal: Principal, d: DeclaracionJurada
) -> DeclaracionOut:
    registro = await session.get(RegistroNotarial, d.registro_id)
    assert registro is not None  # noqa: S101 - FK RESTRICT
    cantidad = d.cantidad_actos
    if cantidad is None:
        cantidad = len(await service.list_actos(session, d.id))
    return DeclaracionOut(
        id=d.id,
        registro=registro_resumen(registro),
        periodo=d.periodo,
        numero_rectificativa=d.numero_rectificativa,
        estado=EstadoDDJJ(d.estado),
        observaciones=d.observaciones,
        fecha_presentacion=d.fecha_presentacion,
        presentada_por=await _actor(session, principal, d.presentada_por_user_id),
        rectifica_a_id=d.rectifica_a_id,
        cantidad_actos=cantidad,
        total_protocolos=d.total_protocolos,
        vencimiento=await service.vencimiento_de(session, d.periodo),
        created_at=d.created_at,
    )


async def declaracion_detalle(
    session: SessionDep, principal: Principal, d: DeclaracionJurada
) -> DeclaracionDetalle:
    base = await declaracion_out(session, principal, d)
    actos = await service.list_actos(session, d.id)
    cargos = await service.cargos_en_periodo(session, d.registro_id, d.periodo)
    boletas = await service.list_boletas(session, d.id)
    por_acto, huecos = await service.controles_ddjj(session, principal, d, actos)
    return DeclaracionDetalle(
        **base.model_dump(),
        actos=[acto_out(a) for a in actos],
        boletas=[await boleta_out(session, principal, b) for b in boletas],
        escribanos=_unicos(cargos),
        puede_operar=await service.puede_operar(session, principal, d.registro_id),
        controles={i: [control_out(c) for c in cs] for i, cs in por_acto.items()},
        huecos=[
            HuecoOut(
                tipo_protocolo=h.tipo_protocolo,
                tramos=[TramoOut(desde=d, hasta=a) for d, a in h.tramos],
                total=h.total,
            )
            for h in huecos
        ],
        proximos_numeros=await service.proximos_numeros(session, d.registro_id, int(d.periodo[:4])),
    )


def control_out(c: protocolo.Control) -> ControlOut:
    return ControlOut(codigo=c.codigo, nivel=c.nivel, mensaje=c.mensaje)


def vencimiento_out(v: Vencimiento) -> VencimientoOut:
    return VencimientoOut(periodo=v.periodo, fecha_vencimiento=v.fecha_vencimiento)


# --------------------------------------------------------------------------- registros


@router.get("/registros", response_model=list[RegistroOperable])
async def registros_operables(principal: CanOperate, session: SessionDep) -> list[RegistroOperable]:
    """Registros cuyas DDJJ puede cargar quien consulta, con sus escribanos con cargo vigente."""
    registros = await service.registros_operables(session, principal)
    out = []
    for r in registros:
        cargos = await service.cargos_en_periodo(session, r.id, service.periodo_de(today_local()))
        out.append(RegistroOperable(**registro_resumen(r).model_dump(), escribanos=_unicos(cargos)))
    return out


# --------------------------------------------------------------------------- vencimientos


@router.get("/vencimientos", response_model=list[VencimientoOut])
async def list_vencimientos(
    _: CanRead,
    session: SessionDep,
    anio: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> list[VencimientoOut]:
    return [vencimiento_out(v) for v in await service.list_vencimientos(session, anio)]


@router.put("/vencimientos/{periodo}", response_model=VencimientoOut)
async def fijar_vencimiento(
    periodo: Periodo,
    body: VencimientoIn,
    principal: CanSetCalendar,
    session: SessionDep,
    ctx: RequestContextDep,
) -> VencimientoOut:
    item = await service.fijar_vencimiento(
        session, ctx, principal.user, periodo, body.fecha_vencimiento
    )
    return vencimiento_out(item)


# --------------------------------------------------------------------------- declaraciones


@router.get("/declaraciones", response_model=Page[DeclaracionOut])
async def list_declaraciones(
    principal: CanRead,
    session: SessionDep,
    page: PageParamsDep,
    registro_id: uuid.UUID | None = None,
    periodo: Annotated[Periodo | None, Query()] = None,
    estado: EstadoDDJJ | None = None,
) -> Page[DeclaracionOut]:
    items, total = await service.list_declaraciones(
        session,
        principal,
        service.FiltroDeclaraciones(registro_id=registro_id, periodo=periodo, estado=estado),
        page,
    )
    return Page(
        items=[await declaracion_out(session, principal, d) for d in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("/declaraciones", response_model=DeclaracionDetalle)
async def abrir_declaracion(
    body: DeclaracionIn,
    principal: CanOperate,
    session: SessionDep,
    ctx: RequestContextDep,
    response: Response,
) -> DeclaracionDetalle:
    """Abre el borrador del registro y período, o devuelve la DDJJ que ya está en curso."""
    item, creada = await service.abrir_declaracion(session, ctx, principal, body)
    response.status_code = 201 if creada else 200
    return await declaracion_detalle(session, principal, item)


@router.get("/declaraciones/{ddjj_id}", response_model=DeclaracionDetalle)
async def get_declaracion(
    ddjj_id: uuid.UUID, principal: CanRead, session: SessionDep
) -> DeclaracionDetalle:
    item = await service.get_declaracion(session, principal, ddjj_id)
    return await declaracion_detalle(session, principal, item)


@router.post("/declaraciones/{ddjj_id}/actos", response_model=ActoOut, status_code=201)
async def agregar_acto(
    ddjj_id: uuid.UUID,
    body: ActoIn,
    principal: CanOperate,
    session: SessionDep,
    ctx: RequestContextDep,
) -> ActoOut:
    return acto_out(await service.agregar_acto(session, ctx, principal, ddjj_id, body))


@router.post("/declaraciones/{ddjj_id}/actos/verificacion", response_model=VerificacionActoOut)
async def verificar_acto(
    ddjj_id: uuid.UUID, body: VerificacionActoIn, principal: CanOperate, session: SessionDep
) -> VerificacionActoOut:
    """Aporte estimado y controles del libro de protocolo mientras se carga un acto."""
    aporte, controles = await service.verificar_acto(session, principal, ddjj_id, body)
    return VerificacionActoOut(aporte=aporte, controles=[control_out(c) for c in controles])


@router.post("/declaraciones/{ddjj_id}/actos/{acto_id}/baja", status_code=204)
async def baja_acto(
    ddjj_id: uuid.UUID,
    acto_id: uuid.UUID,
    body: BajaActo,
    principal: CanOperate,
    session: SessionDep,
    ctx: RequestContextDep,
) -> Response:
    await service.baja_acto(session, ctx, principal, ddjj_id, acto_id, body.motivo)
    return Response(status_code=204)


@router.get("/declaraciones/{ddjj_id}/liquidacion", response_model=LiquidacionOut)
async def liquidacion(
    ddjj_id: uuid.UUID,
    principal: CanRead,
    session: SessionDep,
    fecha_pago: Annotated[date | None, Query(description="Por defecto, hoy")] = None,
) -> LiquidacionOut:
    """Vista previa del borrador con los parámetros vigentes. No guarda nada."""
    item = await service.get_declaracion(session, principal, ddjj_id)
    actos = await service.list_actos(session, item.id)
    pre = await service.preliquidar(session, item, actos, fecha_pago or today_local())
    liq = pre.liquidacion
    return LiquidacionOut(
        aportes=[
            AporteActoOut(acto_id=a.id, aporte=aporte.aporte)
            for a, aporte in zip(actos, liq.aportes, strict=True)
        ],
        vencimiento=pre.vencimiento,
        fecha_pago=pre.fecha_pago,
        total_protocolos=liq.total_protocolos,
        aporte_minimo=liq.aporte_minimo,
        excedente=liq.excedente,
        aporte_medico=liq.aporte_medico,
        cantidad_aportes_medicos=liq.cantidad_aportes_medicos,
        total_en_termino=liq.total_en_termino,
        dias_mora=liq.dias_mora,
        interes_mora=liq.interes_mora,
        tramos_mora=[
            TramoMoraOut(
                desde=t.desde,
                hasta=t.hasta,
                dias=t.dias,
                tasa=t.tasa,
                periodo_tasa=t.periodo_tasa,
                interes=t.interes,
            )
            for t in liq.tramos_mora
        ],
        total_a_pagar=liq.total_a_pagar,
        usa_valores_de_ejemplo=pre.usa_valores_de_ejemplo,
    )


@router.post("/declaraciones/{ddjj_id}/presentar", response_model=BoletaOut, status_code=201)
async def presentar(
    ddjj_id: uuid.UUID,
    body: PresentarIn,
    principal: CanOperate,
    session: SessionDep,
    ctx: RequestContextDep,
) -> BoletaOut:
    """Presenta la DDJJ y emite su boleta."""
    boleta = await service.presentar(session, ctx, principal, ddjj_id, body)
    return await boleta_out(session, principal, boleta)


@router.post("/declaraciones/{ddjj_id}/boletas", response_model=BoletaOut, status_code=201)
async def emitir_boleta(
    ddjj_id: uuid.UUID,
    body: EmitirBoletaIn,
    principal: CanOperate,
    session: SessionDep,
    ctx: RequestContextDep,
) -> BoletaOut:
    """Reemite la boleta para otra fecha de pago; la pendiente anterior queda anulada."""
    boleta = await service.emitir_boleta(session, ctx, principal, ddjj_id, body.fecha_pago)
    return await boleta_out(session, principal, boleta)


@router.post(
    "/declaraciones/{ddjj_id}/rectificar", response_model=DeclaracionDetalle, status_code=201
)
async def rectificar(
    ddjj_id: uuid.UUID, principal: CanOperate, session: SessionDep, ctx: RequestContextDep
) -> DeclaracionDetalle:
    item = await service.rectificar(session, ctx, principal, ddjj_id)
    return await declaracion_detalle(session, principal, item)


# --------------------------------------------------------------------------- boletas


@router.get("/boletas/{boleta_id}", response_model=BoletaOut)
async def get_boleta(
    boleta_id: uuid.UUID, principal: CanReadBoletas, session: SessionDep
) -> BoletaOut:
    boleta = await service.get_boleta(session, principal, boleta_id)
    return await boleta_out(session, principal, boleta)


@router.get(
    "/boletas/{boleta_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def boleta_pdf(
    boleta_id: uuid.UUID, principal: CanReadBoletas, session: SessionDep, settings: SettingsDep
) -> Response:
    boleta = await service.get_boleta(session, principal, boleta_id)
    datos = await service.datos_pdf(session, boleta)
    contenido = await pdf.render_pdf_async(settings, datos)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="boleta-{boleta.numero}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@public_router.get("/verificar/{codigo}", response_model=VerificacionOut)
async def verificar(
    codigo: Annotated[str, Path(pattern=r"^[A-Za-z2-7]{16}$")], session: SessionDep
) -> VerificacionOut:
    """Verificación pública (QR de la boleta): datos mínimos, sin información personal."""
    v = await service.verificar(session, codigo)
    b = v.boleta
    return VerificacionOut(
        numero=b.numero,
        codigo_verificacion=b.codigo_verificacion,
        registro_numero=v.registro_numero,
        periodo=b.periodo,
        estado=EstadoBoleta(b.estado),
        fecha_emision=b.fecha_emision,
        fecha_pago=b.fecha_pago,
        total_a_pagar=b.total_a_pagar,
        integra=v.integra,
    )
