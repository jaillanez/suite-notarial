"""Préstamos a afiliados: /api/v1/prestamos."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.common.dates import today_local
from app.common.deps import SessionDep
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.padron.models import Escribano
from app.modules.pagos import mercadopago, mercadopago_service
from app.modules.pagos.catalog import EstadoPagoMP
from app.modules.pagos.models import PagoMercadoPago
from app.modules.pagos.schemas import InicioPagoMPOut
from app.modules.parametros import service as parametros
from app.modules.prestamos import motor, service
from app.modules.prestamos.catalog import EstadoCuota, EstadoPrestamo, Moneda, Sistema
from app.modules.prestamos.models import CuotaPrestamo, Linea, Prestamo
from app.modules.prestamos.schemas import (
    CobroCuotaMPOut,
    CuotaOut,
    EvaluacionOut,
    LineaIn,
    LineaOut,
    PagoIn,
    PersonaResumen,
    PrestamoDetalle,
    PrestamoOut,
    RechazoIn,
    SimulacionIn,
    SolicitudIn,
    Totales,
)

router = APIRouter(prefix="/prestamos", tags=["prestamos"])

CanRead = Annotated[
    Principal,
    Depends(
        require_any_permission(
            Perm.PRESTAMOS_READ_OWN, Perm.PRESTAMOS_READ_ALL, Perm.PRESTAMOS_MANAGE
        )
    ),
]
CanManage = Annotated[Principal, Depends(require_permissions(Perm.PRESTAMOS_MANAGE))]
CanApprove = Annotated[Principal, Depends(require_permissions(Perm.PRESTAMOS_APPROVE))]
CanCobrar = Annotated[Principal, Depends(require_permissions(Perm.PRESTAMOS_COBRAR))]
CERO = Decimal("0.00")


def linea_out(linea: Linea) -> LineaOut:
    return LineaOut(
        id=linea.id,
        codigo=linea.codigo,
        nombre=linea.nombre,
        descripcion=linea.descripcion,
        sistema=Sistema(linea.sistema),
        plazo_minimo=linea.plazo_minimo,
        plazo_maximo=linea.plazo_maximo,
        monto_minimo=linea.monto_minimo,
        monto_maximo=linea.monto_maximo,
        tna=linea.tna,
        afectacion_maxima=linea.afectacion_maxima,
        requiere_garante=linea.requiere_garante,
        moneda=Moneda(linea.moneda),
        garantia=linea.garantia,
        requisito_conducta=linea.requisito_conducta,
        relacion_capital_hipoteca=linea.relacion_capital_hipoteca,
        requiere_certificado_ingresos=linea.requiere_certificado_ingresos,
        requiere_certificado_bienes=linea.requiere_certificado_bienes,
        antiguedad_minima_meses=linea.antiguedad_minima_meses,
        es_ejemplo=linea.es_ejemplo,
        is_active=linea.is_active,
    )


def persona(e: Escribano) -> PersonaResumen:
    return PersonaResumen(
        id=e.id,
        apellido_nombre=f"{e.persona.apellido}, {e.persona.nombre}",
        matricula_numero=e.matricula_numero,
    )


def cuota_out(c: motor.Cuota | CuotaPrestamo, hoy: date) -> CuotaOut:
    if isinstance(c, CuotaPrestamo):
        return CuotaOut(
            numero=c.numero,
            vencimiento=c.vencimiento,
            saldo_inicial=c.saldo_inicial,
            amortizacion=c.amortizacion,
            interes=c.interes,
            cuota=c.cuota,
            saldo_final=c.saldo_final,
            estado=EstadoCuota(c.estado),
            vencida=c.estado == EstadoCuota.PENDIENTE.value and c.vencimiento < hoy,
            fecha_pago=c.fecha_pago,
            importe_pagado=c.importe_pagado,
        )
    return CuotaOut(
        numero=c.numero,
        vencimiento=c.vencimiento,
        saldo_inicial=c.saldo_inicial,
        amortizacion=c.amortizacion,
        interes=c.interes,
        cuota=c.cuota,
        saldo_final=c.saldo_final,
        estado=EstadoCuota.PENDIENTE,
        vencida=False,
        fecha_pago=None,
        importe_pagado=None,
    )


def totales(cuotas: list[CuotaOut]) -> Totales:
    capital = sum((c.amortizacion for c in cuotas), CERO)
    intereses = sum((c.interes for c in cuotas), CERO)
    return Totales(capital=capital, intereses=intereses, total=capital + intereses)


def evaluacion_out(ev: service.Evaluacion) -> EvaluacionOut:
    hoy = today_local()
    plan = [cuota_out(c, hoy) for c in ev.plan]
    return EvaluacionOut(
        moneda=ev.moneda,
        sistema=ev.sistema,
        tna=ev.tna,
        tasa_es_ejemplo=ev.tasa_es_ejemplo,
        capital=ev.capital,
        cuotas=ev.cuotas,
        cuota_maxima=ev.cuota_maxima,
        otras_cuotas=ev.otras_cuotas,
        afectacion=ev.afectacion,
        afectacion_maxima=ev.afectacion_maxima,
        requiere_garante=ev.requiere_garante,
        impedimentos=ev.impedimentos,
        avisos=ev.avisos,
        plan=plan,
        totales=totales(plan),
    )


async def _solo_garante(session: SessionDep, principal: Principal, p: Prestamo) -> bool:
    """Quien mira es el garante (y no el titular ni personal con acceso a todo)."""
    if service.ve_todo(principal):
        return False
    propio = await service.escribano_de(session, principal.user)
    return propio is not None and propio.id != p.escribano_id


async def prestamo_out(session: SessionDep, principal: Principal, p: Prestamo) -> PrestamoOut:
    escribano = await service.get_escribano(session, p.escribano_id)
    garante = (
        await service.get_escribano(session, p.garante_escribano_id)
        if p.garante_escribano_id
        else None
    )
    linea = await service.get_linea(session, p.linea_id)
    cuotas = await service.plan_guardado(session, p.id)
    hoy = today_local()
    ids = {p.creado_por_user_id} | ({p.resuelto_por_user_id} if p.resuelto_por_user_id else set())
    emails = await parametros.user_emails(session, ids) if service.ve_todo(principal) else {}
    pendientes = [c for c in cuotas if c.estado == EstadoCuota.PENDIENTE.value]
    # El garante responde por la deuda (ve plan, saldo y atrasos) pero no la situación económica
    # del titular ni las notas internas de la evaluación.
    reservado = await _solo_garante(session, principal, p)
    return PrestamoOut(
        id=p.id,
        numero=p.numero,
        escribano=persona(escribano),
        garante=persona(garante) if garante else None,
        linea_id=linea.id,
        linea_nombre=linea.nombre,
        estado=EstadoPrestamo(p.estado),
        moneda=Moneda(p.moneda),
        sistema=Sistema(p.sistema),
        tna=p.tna,
        tasa_es_ejemplo=p.tasa_es_ejemplo,
        capital=p.capital,
        cuotas=p.cuotas,
        ingreso_neto=None if reservado else p.ingreso_neto,
        otras_cuotas=None if reservado else p.otras_cuotas,
        cuota_maxima=p.cuota_maxima,
        afectacion=None if reservado else p.afectacion,
        afectacion_maxima=p.afectacion_maxima,
        observaciones=None if reservado else p.observaciones,
        motivo_rechazo=p.motivo_rechazo,
        fecha_otorgamiento=p.fecha_otorgamiento,
        # A un escribano no se le muestran los correos del personal.
        creado_por=emails.get(p.creado_por_user_id, "Caja Notarial"),
        resuelto_por=(
            emails.get(p.resuelto_por_user_id, "Caja Notarial") if p.resuelto_por_user_id else None
        ),
        resuelto_en=p.resuelto_en,
        created_at=p.created_at,
        saldo_capital=pendientes[0].saldo_inicial if pendientes else (CERO if cuotas else None),
        cuotas_pagadas=len(cuotas) - len(pendientes),
        cuotas_vencidas=sum(1 for c in pendientes if c.vencimiento < hoy),
    )


async def _puede_resolver(session: SessionDep, principal: Principal, p: Prestamo) -> bool:
    """Mismas reglas que el servicio: otra persona, con permiso, que no sea titular ni garante."""
    if (
        p.estado != EstadoPrestamo.SOLICITADO.value
        or Perm.PRESTAMOS_APPROVE.value not in principal.permissions
        or p.creado_por_user_id == principal.user.id
    ):
        return False
    propio = await service.escribano_de(session, principal.user)
    return propio is None or propio.id not in (p.escribano_id, p.garante_escribano_id)


async def prestamo_detalle(
    session: SessionDep, principal: Principal, p: Prestamo
) -> PrestamoDetalle:
    base = await prestamo_out(session, principal, p)
    hoy = today_local()
    impedimentos: list[str] = []
    avisos: list[str] = []
    if p.estado == EstadoPrestamo.SOLICITADO.value:
        ev = await service.reevaluar(session, p, hoy)
        plan = [cuota_out(c, hoy) for c in ev.plan]
        # Solo el personal ve la situación del garante; el titular, un aviso genérico, y el
        # garante, nada de la evaluación del titular.
        if service.ve_todo(principal):
            impedimentos = ev.impedimentos
            avisos = ev.avisos
        elif not await _solo_garante(session, principal, p):
            impedimentos = ev.impedimentos_para_titular()
            avisos = ev.avisos
    else:
        plan = [cuota_out(c, hoy) for c in await service.plan_guardado(session, p.id)]
    # Los pagos con Mercado Pago son del titular: el garante no los ve (sí la cuota pagada).
    cobros = (
        []
        if await _solo_garante(session, principal, p)
        else [
            c
            for c in await mercadopago_service.de_prestamo(session, p.id)
            if c.estado != EstadoPagoMP.CREADO.value
        ]
    )
    numeros = {c.id: c.numero for c in await service.plan_guardado(session, p.id)}
    return PrestamoDetalle(
        **base.model_dump(),
        plan=plan,
        totales=totales(plan),
        impedimentos_actuales=impedimentos,
        avisos_actuales=avisos,
        puede_resolver=await _puede_resolver(session, principal, p),
        cobros_mp=[
            CobroCuotaMPOut(
                id=c.id,
                cuota=numeros[c.cuota_id],
                estado=c.estado,
                medio_pago=c.medio_pago,
                importe_pagado=c.importe_pagado,
                aprobado_en=c.aprobado_en,
                confirmado_en=c.confirmado_en,
                a_confirmar=c.estado == EstadoPagoMP.APPROVED.value and c.confirmado_en is None,
            )
            for c in cobros
            if c.cuota_id in numeros
        ],
        puede_pagar_mp=await _puede_pagar_mp(session, principal, p, cobros),
    )


async def _puede_pagar_mp(
    session: SessionDep, principal: Principal, p: Prestamo, cobros: list[PagoMercadoPago]
) -> bool:
    """Las mismas condiciones que `mercadopago_service.iniciar_cuota`, para mostrar el botón."""
    if (
        p.estado != EstadoPrestamo.OTORGADO.value
        or p.moneda != Moneda.ARS.value
        or not mercadopago.configurado()
    ):
        return False
    propio = await service.escribano_de(session, principal.user)
    if propio is None or propio.id != p.escribano_id:
        return False
    plan = await service.plan_guardado(session, p.id)
    proxima = next((c for c in plan if c.estado == EstadoCuota.PENDIENTE.value), None)
    return proxima is not None and not any(
        c.cuota_id == proxima.id
        and c.estado == EstadoPagoMP.APPROVED.value
        and c.confirmado_en is None
        for c in cobros
    )
    return False


# --------------------------------------------------------------------------- líneas


@router.get("/lineas", response_model=list[LineaOut])
async def list_lineas(principal: CanRead, session: SessionDep) -> list[LineaOut]:
    gestiona = Perm.PRESTAMOS_MANAGE.value in principal.permissions
    return [linea_out(x) for x in await service.list_lineas(session, solo_activas=not gestiona)]


@router.post("/lineas", response_model=LineaOut, status_code=201)
async def crear_linea(
    body: LineaIn, principal: CanManage, session: SessionDep, ctx: RequestContextDep
) -> LineaOut:
    return linea_out(await service.guardar_linea(session, ctx, principal.user, body))


@router.put("/lineas/{linea_id}", response_model=LineaOut)
async def actualizar_linea(
    linea_id: uuid.UUID,
    body: LineaIn,
    principal: CanManage,
    session: SessionDep,
    ctx: RequestContextDep,
) -> LineaOut:
    return linea_out(await service.guardar_linea(session, ctx, principal.user, body, linea_id))


# --------------------------------------------------------------------------- simulación


@router.post("/simular", response_model=EvaluacionOut)
async def simular(body: SimulacionIn, principal: CanRead, session: SessionDep) -> EvaluacionOut:
    """Plan de cuotas y evaluación. No guarda nada. El escribano simula para sí mismo."""
    linea = await service.get_linea(session, body.linea_id)
    garante_id = body.garante_escribano_id
    if service.ve_todo(principal) or Perm.PRESTAMOS_MANAGE.value in principal.permissions:
        escribano = (
            await service.get_escribano(session, body.escribano_id) if body.escribano_id else None
        )
    else:
        escribano = await service.escribano_de(session, principal.user)
        # Un escribano no evalúa a terceros: sondear un garante revelaría sus deudas o su mora.
        garante_id = None
    ev = await service.evaluar(
        session,
        linea,
        capital=body.capital,
        cuotas=body.cuotas,
        hoy=today_local(),
        escribano=escribano,
        ingreso_neto=body.ingreso_neto,
        garante_id=garante_id,
    )
    return evaluacion_out(ev)


# --------------------------------------------------------------------------- préstamos


@router.get("", response_model=list[PrestamoOut])
async def list_prestamos(
    principal: CanRead,
    session: SessionDep,
    estado: EstadoPrestamo | None = None,
    escribano_id: uuid.UUID | None = None,
) -> list[PrestamoOut]:
    items = await service.list_prestamos(session, principal, estado, escribano_id)
    return [await prestamo_out(session, principal, p) for p in items]


@router.post("", response_model=PrestamoDetalle, status_code=201)
async def crear_solicitud(
    body: SolicitudIn, principal: CanManage, session: SessionDep, ctx: RequestContextDep
) -> PrestamoDetalle:
    """Carga la solicitud evaluada. La otorga o rechaza otra persona (cuatro ojos)."""
    p = await service.crear_solicitud(session, ctx, principal.user, body)
    return await prestamo_detalle(session, principal, p)


@router.get("/{prestamo_id}", response_model=PrestamoDetalle)
async def get_prestamo(
    prestamo_id: uuid.UUID, principal: CanRead, session: SessionDep
) -> PrestamoDetalle:
    p = await service.get_prestamo(session, principal, prestamo_id)
    return await prestamo_detalle(session, principal, p)


@router.post("/{prestamo_id}/otorgar", response_model=PrestamoDetalle)
async def otorgar(
    prestamo_id: uuid.UUID, principal: CanApprove, session: SessionDep, ctx: RequestContextDep
) -> PrestamoDetalle:
    """Reevalúa con los datos de hoy y genera el plan de cuotas definitivo."""
    p = await service.otorgar(session, ctx, principal, prestamo_id)
    return await prestamo_detalle(session, principal, p)


@router.post("/{prestamo_id}/rechazar", response_model=PrestamoDetalle)
async def rechazar(
    prestamo_id: uuid.UUID,
    body: RechazoIn,
    principal: CanApprove,
    session: SessionDep,
    ctx: RequestContextDep,
) -> PrestamoDetalle:
    p = await service.rechazar(session, ctx, principal, prestamo_id, body.motivo)
    return await prestamo_detalle(session, principal, p)


@router.post("/{prestamo_id}/cuotas/{numero}/pago", response_model=PrestamoDetalle)
async def registrar_pago(
    prestamo_id: uuid.UUID,
    numero: Annotated[int, Path(ge=1, le=360)],
    body: PagoIn,
    principal: CanCobrar,
    session: SessionDep,
    ctx: RequestContextDep,
) -> PrestamoDetalle:
    p = await service.registrar_pago(
        session, ctx, principal, prestamo_id, numero, body.fecha_pago, body.importe
    )
    return await prestamo_detalle(session, principal, p)


# --------------------------------------------------------------------------- Mercado Pago


@router.post("/{prestamo_id}/mercadopago", response_model=InicioPagoMPOut, status_code=201)
async def pagar_cuota_con_mercadopago(
    prestamo_id: uuid.UUID, principal: CanRead, session: SessionDep, ctx: RequestContextDep
) -> InicioPagoMPOut:
    """Cobro de la próxima cuota con Mercado Pago (solo quien tomó el préstamo)."""
    preferencia = await mercadopago_service.iniciar_cuota(session, ctx, principal, prestamo_id)
    return InicioPagoMPOut(url_pago=preferencia.url_pago)


@router.post("/{prestamo_id}/mercadopago/{pago_id}/confirmar", response_model=PrestamoDetalle)
async def confirmar_cobro_mp(
    prestamo_id: uuid.UUID,
    pago_id: uuid.UUID,
    principal: CanCobrar,
    session: SessionDep,
    ctx: RequestContextDep,
) -> PrestamoDetalle:
    """Tesorería confirma el pago con Mercado Pago: la cuota pasa a pagada."""
    p = await service.confirmar_cobro_mp(session, ctx, principal, prestamo_id, pago_id)
    return await prestamo_detalle(session, principal, p)
