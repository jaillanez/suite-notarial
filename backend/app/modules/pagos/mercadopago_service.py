"""Pago de boletas con Mercado Pago (Checkout Pro), bajo la regla PAGO.

1. El escribano pide pagar una boleta pendiente: se arma un cobro por el total exacto (la
   comisión la absorbe la Caja) que vence con la fecha de pago de la boleta.
2. Mercado Pago informa el pago (al volver del pago o por notificación). La Suite NO toma el
   estado del navegador ni de la notificación: consulta el pago a la API con el token de la Caja
   y recién ahí lo registra en `pagos_mercadopago`.
3. Un pago aprobado genera un comprobante de origen MERCADO_PAGO en la mesa de Tesorería, con
   el importe y la fecha que informó Mercado Pago. La boleta pasa a PAGADA recién cuando
   Tesorería lo confirma, como cualquier comprobante.

Todo cambio de estado queda en la auditoría.
"""

import uuid
from datetime import UTC, datetime, time
from http import HTTPStatus
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.money import format_pesos
from app.common.pagination import PageParams
from app.core.config import get_settings
from app.core.errors import ProblemError
from app.modules.ddjj import service as ddjj_service
from app.modules.ddjj.catalog import EstadoBoleta
from app.modules.ddjj.models import Boleta
from app.modules.iam.deps import Principal
from app.modules.padron.models import RegistroNotarial
from app.modules.pagos import mercadopago
from app.modules.pagos.catalog import (
    ESTADOS_MP_REVERTIDOS,
    EstadoComprobante,
    EstadoPagoMP,
    OrigenComprobante,
)
from app.modules.pagos.models import Comprobante, PagoMercadoPago

ZONA = ZoneInfo("America/Argentina/San_Juan")
PENDIENTE = EstadoComprobante.PENDIENTE_REVISION.value
APROBADO = EstadoPagoMP.APPROVED.value


def _no_disponible() -> ProblemError:
    return ProblemError(
        HTTPStatus.SERVICE_UNAVAILABLE,
        "El pago con Mercado Pago no está disponible en este momento: probá más tarde o pagá "
        "por transferencia y adjuntá el comprobante.",
    )


def _url_web(ruta: str) -> str:
    return f"{get_settings().public_web_base}{ruta}"


# --------------------------------------------------------------------------- inicio del pago


async def iniciar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, boleta_id: uuid.UUID
) -> mercadopago.Preferencia:
    if not mercadopago.configurado():
        raise _no_disponible()
    boleta = await ddjj_service.get_boleta(session, principal, boleta_id, lock=True)
    if boleta.estado != EstadoBoleta.PENDIENTE.value:
        estado = "pagada" if boleta.estado == EstadoBoleta.PAGADA.value else "anulada"
        raise ProblemError(HTTPStatus.CONFLICT, f"La boleta N° {boleta.numero} está {estado}.")
    en_curso = await session.scalar(
        select(func.count()).where(
            Comprobante.boleta_id == boleta.id,
            Comprobante.estado.in_((PENDIENTE, EstadoComprobante.APROBADO.value)),
        )
    )
    if en_curso:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "Esta boleta ya tiene un pago en revisión por Tesorería: esperá su confirmación.",
        )
    if boleta.fecha_pago < today_local():
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "La fecha de pago de la boleta ya pasó: emití una nueva con la fecha de hoy.",
        )
    registro = await session.get(RegistroNotarial, boleta.registro_id)
    assert registro is not None  # noqa: S101 - FK RESTRICT
    pago_id = uuid.uuid4()
    settings = get_settings()
    https = settings.public_web_base.startswith("https://")
    vence = datetime.combine(boleta.fecha_pago, time(23, 59, 59), tzinfo=ZONA)
    try:
        preferencia = await mercadopago.crear_preferencia(
            referencia=str(pago_id),
            titulo=(
                f"Boleta N° {boleta.numero} · Registro N° {registro.numero_registro} · "
                f"{boleta.periodo[5:7]}/{boleta.periodo[:4]}"
            ),
            importe=boleta.total_a_pagar,
            vence=vence,
            url_retorno=_url_web(f"/pagos/mercadopago/retorno?pago={pago_id}"),
            # Mercado Pago solo notifica a una dirección pública con HTTPS.
            url_notificacion=(
                _url_web("/api/v1/pagos/mercadopago/notificaciones") if https else None
            ),
            retorno_automatico=https,
        )
    except mercadopago.MercadoPagoError as exc:
        raise _no_disponible() from exc
    session.add(
        PagoMercadoPago(
            id=pago_id,
            boleta_id=boleta.id,
            preference_id=preferencia.id,
            importe_boleta=boleta.total_a_pagar,
            iniciado_por_user_id=principal.user.id,
            estado=EstadoPagoMP.CREADO.value,
        )
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PAGO_MP_INICIADO,
        actor_user_id=principal.user.id,
        details={
            "pago_mp_id": str(pago_id),
            "boleta": boleta.numero,
            "importe": f"{boleta.total_a_pagar:.2f}",
            "vence": vence.isoformat(),
        },
    )
    await session.commit()
    return preferencia


# --------------------------------------------------------------------------- registro del pago


async def _registro_de(session: AsyncSession, referencia: str | None) -> PagoMercadoPago | None:
    try:
        pago_id = uuid.UUID(referencia or "")
    except ValueError:
        return None
    return (
        (
            await session.execute(
                select(PagoMercadoPago)
                .where(PagoMercadoPago.id == pago_id)
                .with_for_update(of=PagoMercadoPago)
            )
        )
        .scalars()
        .first()
    )


async def registrar(
    session: AsyncSession, ctx: RequestContext, pago: mercadopago.Pago
) -> PagoMercadoPago | None:
    """Registra lo que informa Mercado Pago de un pago (idempotente). Devuelve el registro, o
    None si el pago no es de un cobro armado por la Suite."""
    item = await _registro_de(session, pago.referencia)
    if item is None:
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_MP_DESCONOCIDO,
            severity=Severity.WARNING,
            details={"mp_payment_id": pago.id, "referencia": (pago.referencia or "")[:100]},
        )
        await session.commit()
        return None
    if item.mp_payment_id not in (None, pago.id) and item.estado == APROBADO:
        # Otro pago sobre un cobro ya aprobado: un rechazo no lo pisa; un segundo aprobado es
        # un pago doble y Tesorería tiene que verlo (no se crea otro comprobante).
        if pago.estado == APROBADO:
            record_audit(
                session,
                ctx,
                AuditEvent.PAGO_MP_DUPLICADO,
                severity=Severity.CRITICAL,
                details={
                    "pago_mp_id": str(item.id),
                    "mp_payment_id": pago.id,
                    "mp_payment_id_registrado": item.mp_payment_id,
                    "importe": f"{pago.importe:.2f}" if pago.importe is not None else None,
                },
            )
            await session.commit()
        return item
    antes = {"estado": item.estado, "mp_payment_id": item.mp_payment_id}
    estado_anterior = item.estado
    try:
        estado = EstadoPagoMP(pago.estado)
    except ValueError:
        estado = EstadoPagoMP.PENDING
    item.estado = estado.value
    item.mp_payment_id = pago.id
    item.estado_detalle = pago.estado_detalle
    item.medio_pago = pago.medio_pago
    item.importe_pagado = pago.importe
    item.comision = pago.comision
    item.importe_neto = pago.neto
    item.aprobado_en = pago.aprobado_en
    item.updated_at = datetime.now(UTC)
    if item.estado == estado_anterior and item.estado != APROBADO:
        await session.commit()
        return item

    boleta = await session.get(Boleta, item.boleta_id)
    assert boleta is not None  # noqa: S101 - FK RESTRICT
    detalles = {
        "pago_mp_id": str(item.id),
        "mp_payment_id": pago.id,
        "boleta": boleta.numero,
        "estado": item.estado,
        "importe_pagado": f"{pago.importe:.2f}" if pago.importe is not None else None,
        "comision": f"{pago.comision:.2f}" if pago.comision is not None else None,
    }
    if estado is EstadoPagoMP.APPROVED and item.comprobante_id is None:
        await _comprobante_para_tesoreria(session, ctx, item, boleta, pago, detalles)
    elif estado in ESTADOS_MP_REVERTIDOS and estado_anterior == APROBADO:
        # TODO(negocio): procedimiento ante una devolución o un desconocimiento posterior.
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_MP_REVERTIDO,
            severity=Severity.CRITICAL,
            old_value=antes,
            new_value={"estado": item.estado},
            details=detalles,
        )
    elif item.estado != estado_anterior:
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_MP_ACTUALIZADO,
            old_value=antes,
            new_value={"estado": item.estado},
            details=detalles,
        )
    await session.commit()
    return item


async def _comprobante_para_tesoreria(
    session: AsyncSession,
    ctx: RequestContext,
    item: PagoMercadoPago,
    boleta: Boleta,
    pago: mercadopago.Pago,
    detalles: dict[str, object],
) -> None:
    coincide = (
        pago.moneda == "ARS" and pago.importe is not None and pago.importe == boleta.total_a_pagar
    )
    en_revision = await session.scalar(
        select(Comprobante.id).where(
            Comprobante.boleta_id == boleta.id, Comprobante.estado == PENDIENTE
        )
    )
    if en_revision is not None or boleta.estado != EstadoBoleta.PENDIENTE.value:
        # La boleta ya tiene otro pago en revisión (o ya no está pendiente): el pago queda
        # registrado para que Tesorería lo vea, sin un segundo comprobante.
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_MP_SIN_COMPROBANTE,
            severity=Severity.CRITICAL,
            details={**detalles, "boleta_estado": boleta.estado},
        )
        return
    comprobante = Comprobante(
        id=uuid.uuid4(),
        boleta_id=boleta.id,
        registro_id=boleta.registro_id,
        periodo=boleta.periodo,
        origen=OrigenComprobante.MERCADO_PAGO.value,
        fecha_transferencia=pago.fecha_aprobacion or today_local(),
        banco_origen="Mercado Pago",
        numero_operacion=pago.id,
        importe_declarado=pago.importe if pago.importe is not None else boleta.total_a_pagar,
        estado=PENDIENTE,
        subido_por_user_id=item.iniciado_por_user_id,
    )
    session.add(comprobante)
    await session.flush()
    item.comprobante_id = comprobante.id
    record_audit(
        session,
        ctx,
        AuditEvent.PAGO_MP_ACREDITADO,
        severity=Severity.INFO if coincide else Severity.WARNING,
        target_user_id=item.iniciado_por_user_id,
        new_value={"estado": PENDIENTE, "origen": OrigenComprobante.MERCADO_PAGO.value},
        details={
            **detalles,
            "comprobante_id": str(comprobante.id),
            "importe_coincide": coincide,
            "total_boleta": format_pesos(boleta.total_a_pagar),
        },
    )


async def sincronizar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, pago_mp_id: uuid.UUID
) -> PagoMercadoPago:
    """Al volver de Mercado Pago: consulta los pagos del cobro y los registra."""
    item = await session.get(PagoMercadoPago, pago_mp_id)
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El pago no existe.")
    # Solo quien puede ver la boleta (el mismo control que para la boleta).
    await ddjj_service.get_boleta(session, principal, item.boleta_id)
    await session.commit()
    try:
        pagos = await mercadopago.pagos_de(str(item.id))
    except mercadopago.MercadoPagoError as exc:
        raise _no_disponible() from exc
    # Los aprobados al final: si hubo un intento rechazado antes, queda registrado el aprobado.
    for pago in sorted(pagos, key=lambda p: p.estado == APROBADO):
        await registrar(session, ctx, pago)
    actualizado = await session.get(PagoMercadoPago, pago_mp_id, populate_existing=True)
    assert actualizado is not None  # noqa: S101 - recién leído
    return actualizado


async def notificacion(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    tipo: str | None,
    data_id: str | None,
    firma: str | None,
    request_id: str | None,
) -> None:
    """Notificación de Mercado Pago (webhook). Si hay clave secreta configurada, se exige la
    firma; en cualquier caso el pago se consulta a la API (la notificación no se cree)."""
    if tipo != "payment" or not data_id or not data_id.isdigit():
        return
    configurada = get_settings().MERCADOPAGO_WEBHOOK_SECRET
    secreto = configurada.get_secret_value().strip() if configurada is not None else ""
    if secreto and not mercadopago.firma_valida(
        firma=firma, request_id=request_id, data_id=data_id, secreto=secreto
    ):
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_MP_FIRMA_INVALIDA,
            severity=Severity.WARNING,
            details={"mp_payment_id": data_id},
        )
        await session.commit()
        raise ProblemError(HTTPStatus.UNAUTHORIZED, "Firma inválida.")
    try:
        pago = await mercadopago.obtener_pago(data_id)
    except mercadopago.MercadoPagoError as exc:
        # Mercado Pago reintenta la notificación si no respondemos 2xx.
        raise _no_disponible() from exc
    await registrar(session, ctx, pago)


# --------------------------------------------------------------------------- consulta


async def de_boleta(
    session: AsyncSession, principal: Principal, boleta_id: uuid.UUID
) -> list[PagoMercadoPago]:
    await ddjj_service.get_boleta(session, principal, boleta_id)
    resultado = await session.scalars(
        select(PagoMercadoPago)
        .where(PagoMercadoPago.boleta_id == boleta_id)
        .order_by(PagoMercadoPago.created_at.desc())
    )
    return list(resultado.all())


async def de_comprobante(
    session: AsyncSession, comprobante_id: uuid.UUID
) -> PagoMercadoPago | None:
    return await session.scalar(
        select(PagoMercadoPago).where(PagoMercadoPago.comprobante_id == comprobante_id)
    )


async def registro(
    session: AsyncSession, page: PageParams, *, solo_informados: bool = True
) -> tuple[list[PagoMercadoPago], int]:
    """Registro de pagos con Mercado Pago para Tesorería (los más recientes primero)."""
    stmt = select(PagoMercadoPago)
    if solo_informados:
        stmt = stmt.where(PagoMercadoPago.mp_payment_id.is_not(None))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    filas = await session.scalars(
        stmt.order_by(PagoMercadoPago.updated_at.desc()).offset(page.offset).limit(page.page_size)
    )
    return list(filas.all()), int(total or 0)
