"""Pago de boletas con el botón de pagos Supervielle, bajo la regla PAGO.

1. El escribano pide pagar una boleta pendiente: se publica en el banco una deuda por el total
   exacto que vence con la fecha de pago de la boleta, y se lo lleva al link de pago. Mientras esa
   deuda siga vigente se reutiliza su link: el banco no permite anularla y dos links de la misma
   boleta serían dos pagos posibles.
2. El banco avisa el pago (o el escribano vuelve y toca «Ya pagué»). El aviso no viene firmado:
   la Suite NO toma nada de él ni del navegador; consulta el estado de la publicación a la API con
   sus credenciales y recién ahí lo registra en `pagos_supervielle`.
3. Un pago aprobado genera un comprobante de origen SUPERVIELLE en la mesa de Tesorería, con el
   importe y la fecha que informó el banco. La boleta pasa a PAGADA recién cuando Tesorería lo
   confirma, como cualquier comprobante.

Las cuotas de préstamo en pesos siguen el mismo camino hasta el paso 3 (decisión de la Caja del
17/11/2026): se publica la próxima cuota por su importe exacto (la comisión la absorbe la Caja) y
un pago hecho queda a confirmar por Tesorería desde el préstamo, sin comprobante en la mesa (la
mesa es de boletas), igual que con Mercado Pago. Recién al confirmarlo la cuota pasa a pagada
(`prestamos.service.confirmar_cobro_spv`). Las cuotas en dólares no se publican: el botón cobra
en pesos.

Todo cambio de estado queda en la auditoría.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, AuditSecurityLog, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.money import format_pesos
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.ddjj import service as ddjj_service
from app.modules.ddjj.catalog import EstadoBoleta
from app.modules.ddjj.models import Boleta
from app.modules.iam.deps import Principal
from app.modules.padron.models import RegistroNotarial
from app.modules.pagos import comisiones_spv, supervielle
from app.modules.pagos.catalog import (
    ESTADOS_SPV_EFECTIVOS,
    ESTADOS_SPV_REVERTIDOS,
    EstadoComprobante,
    EstadoPagoMP,
    EstadoPagoSPV,
    OrigenComprobante,
)
from app.modules.pagos.models import (
    SECUENCIA_PUBLICACION_SPV,
    Comprobante,
    PagoMercadoPago,
    PagoSupervielle,
)
from app.modules.pagos.schemas import CuotaCobradaOut
from app.modules.prestamos import service as prestamos_service
from app.modules.prestamos.catalog import EstadoPrestamo, Moneda
from app.modules.prestamos.models import CuotaPrestamo, Prestamo

ZONA = ZoneInfo("America/Argentina/San_Juan")
logger = logging.getLogger(__name__)
# A lo sumo una consulta al banco por publicación en este lapso, venga de donde venga el aviso
# (lo controla la base: vale para todos los procesos). Un aviso que llega dentro de la pausa no
# se descarta: queda marcado en la fila (`aviso_pendiente_en`) antes de responder 200, y lo
# procesa `procesar_avisos_pendientes` (cron cada 2 minutos). Nada vive en memoria.
PAUSA_AVISO = timedelta(seconds=15)
PENDIENTE = EstadoComprobante.PENDIENTE_REVISION.value
EFECTIVOS = {e.value for e in ESTADOS_SPV_EFECTIVOS}


def _no_disponible(
    alternativa: str = "pagá por transferencia y adjuntá el comprobante",
) -> ProblemError:
    return ProblemError(
        HTTPStatus.SERVICE_UNAVAILABLE,
        f"El botón de pagos Supervielle no está disponible en este momento: probá más tarde o "
        f"{alternativa}.",
    )


CUOTA_POR_TESORERIA = "pagale la cuota a Tesorería"


# --------------------------------------------------------------------------- inicio del pago


async def _vigente(session: AsyncSession, boleta: Boleta) -> PagoSupervielle | None:
    """Deuda ya publicada de la boleta que todavía se puede pagar con su link."""
    return await session.scalar(
        select(PagoSupervielle)
        .where(
            PagoSupervielle.boleta_id == boleta.id,
            PagoSupervielle.estado == EstadoPagoSPV.CREADO.value,
            PagoSupervielle.vence == boleta.fecha_pago,
            PagoSupervielle.importe_boleta == boleta.total_a_pagar,
        )
        .order_by(PagoSupervielle.created_at.desc())
        .limit(1)
    )


async def iniciar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, boleta_id: uuid.UUID
) -> PagoSupervielle:
    if not supervielle.configurado():
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
    en_proceso = await session.scalar(
        select(func.count()).where(
            PagoSupervielle.boleta_id == boleta.id,
            PagoSupervielle.estado == EstadoPagoSPV.PENDIENTE.value,
        )
    )
    if en_proceso:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "Esta boleta tiene un pago con Supervielle en proceso: esperá a que el banco lo "
            "acredite.",
        )
    hoy = today_local()
    if boleta.fecha_pago < hoy:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "La fecha de pago de la boleta ya pasó: emití una nueva con la fecha de hoy.",
        )
    if boleta.fecha_pago == hoy:
        # El banco exige que el vencimiento sea posterior al día de la publicación.
        # TODO(banco): confirmar si acepta un vencimiento en el mismo día.
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "El botón Supervielle no acepta boletas que vencen hoy: pagá por transferencia y "
            "adjuntá el comprobante.",
        )
    vigente = await _vigente(session, boleta)
    if vigente is not None:
        await session.commit()
        return vigente

    registro = await session.get(RegistroNotarial, boleta.registro_id)
    assert registro is not None  # noqa: S101 - FK RESTRICT
    pago_id = uuid.uuid4()
    id_publicacion = int(
        (await session.execute(text(f"SELECT nextval('{SECUENCIA_PUBLICACION_SPV}')"))).scalar_one()
    )
    periodo = f"{boleta.periodo[5:7]}/{boleta.periodo[:4]}"
    try:
        publicacion = await supervielle.publicar(
            id_publicacion=id_publicacion,
            importe=boleta.total_a_pagar,
            vence=boleta.fecha_pago,
            nombre=f"Registro Notarial N° {registro.numero_registro}",
            descripcion=f"Caja Notarial · Boleta N° {boleta.numero} · Aportes {periodo}",
            identificadores=[str(pago_id), f"boleta-{boleta.numero}"],
        )
    except supervielle.SupervielleError as exc:
        raise _no_disponible() from exc
    item = PagoSupervielle(
        id=pago_id,
        boleta_id=boleta.id,
        id_publicacion=id_publicacion,
        hash=publicacion.hash,
        link_pago=publicacion.link_pago,
        importe_boleta=boleta.total_a_pagar,
        vence=boleta.fecha_pago,
        iniciado_por_user_id=principal.user.id,
        estado=EstadoPagoSPV.CREADO.value,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PAGO_SPV_INICIADO,
        actor_user_id=principal.user.id,
        details={
            "pago_spv_id": str(pago_id),
            "id_publicacion": id_publicacion,
            "hash": publicacion.hash,
            "boleta": boleta.numero,
            "importe": f"{boleta.total_a_pagar:.2f}",
            "vence": boleta.fecha_pago.isoformat(),
        },
    )
    await session.commit()
    return item


async def _vigente_cuota(
    session: AsyncSession, cuota: CuotaPrestamo, hoy: date
) -> PagoSupervielle | None:
    """Deuda ya publicada de la cuota que todavía se puede pagar con su link."""
    return await session.scalar(
        select(PagoSupervielle)
        .where(
            PagoSupervielle.cuota_id == cuota.id,
            PagoSupervielle.estado == EstadoPagoSPV.CREADO.value,
            PagoSupervielle.vence >= hoy,
            PagoSupervielle.importe_boleta == cuota.cuota,
        )
        .order_by(PagoSupervielle.created_at.desc())
        .limit(1)
    )


async def iniciar_cuota(
    session: AsyncSession, ctx: RequestContext, principal: Principal, prestamo_id: uuid.UUID
) -> PagoSupervielle:
    """Publica la próxima cuota del préstamo (en pesos). La paga solo el escribano que lo tomó,
    por el importe exacto de la cuota: la comisión la absorbe la Caja."""
    if not supervielle.configurado():
        raise _no_disponible(CUOTA_POR_TESORERIA)
    prestamo = await prestamos_service.get_prestamo(session, principal, prestamo_id, lock=True)
    propio = await prestamos_service.escribano_de(session, principal.user)
    if propio is None or propio.id != prestamo.escribano_id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "La cuota la paga con el botón Supervielle quien tomó el préstamo.",
        )
    if prestamo.estado != EstadoPrestamo.OTORGADO.value:
        raise ProblemError(HTTPStatus.CONFLICT, "El préstamo no tiene cuotas para pagar.")
    if prestamo.moneda != Moneda.ARS.value:
        # TODO(negocio): cobro de cuotas en dólares (el botón cobra en pesos).
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "El botón Supervielle cobra en pesos: las cuotas en dólares no se pueden pagar con "
            "él. Consultá a Tesorería.",
        )
    plan = await prestamos_service.plan_guardado(session, prestamo.id)
    cuota = next((c for c in plan if c.estado == prestamos_service.PENDIENTE), None)
    if cuota is None:
        raise ProblemError(HTTPStatus.CONFLICT, "El préstamo no tiene cuotas pendientes.")
    if (medio := await prestamos_service.cobro_a_confirmar(session, cuota.id)) is not None:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            f"La cuota N° {cuota.numero} ya está pagada con {medio} y Tesorería la está "
            "confirmando.",
        )
    en_proceso = await session.scalar(
        select(func.count()).where(
            PagoSupervielle.cuota_id == cuota.id,
            PagoSupervielle.estado == EstadoPagoSPV.PENDIENTE.value,
        )
    )
    if en_proceso:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "Esta cuota tiene un pago con Supervielle en proceso: esperá a que el banco lo "
            "acredite.",
        )
    hoy = today_local()
    vigente = await _vigente_cuota(session, cuota, hoy)
    if vigente is not None:
        await session.commit()
        return vigente

    # El banco exige que el vencimiento sea posterior al día de la publicación: una cuota que
    # vence hoy o ya venció se publica con vencimiento mañana.
    # TODO(banco): confirmar si acepta un vencimiento en el mismo día.
    # TODO(negocio): interés punitorio por pago fuera de término. Mientras no esté definido se
    # cobra la cuota del plan.
    vence = max(cuota.vencimiento, hoy + timedelta(days=1))
    pago_id = uuid.uuid4()
    id_publicacion = int(
        (await session.execute(text(f"SELECT nextval('{SECUENCIA_PUBLICACION_SPV}')"))).scalar_one()
    )
    try:
        publicacion = await supervielle.publicar(
            id_publicacion=id_publicacion,
            importe=cuota.cuota,
            vence=vence,
            nombre=f"Préstamo N° {prestamo.numero}",
            descripcion=(
                f"Caja Notarial · Préstamo N° {prestamo.numero} · Cuota {cuota.numero} de "
                f"{prestamo.cuotas}"
            ),
            identificadores=[str(pago_id), f"prestamo-{prestamo.numero}-cuota-{cuota.numero}"],
        )
    except supervielle.SupervielleError as exc:
        raise _no_disponible(CUOTA_POR_TESORERIA) from exc
    item = PagoSupervielle(
        id=pago_id,
        cuota_id=cuota.id,
        id_publicacion=id_publicacion,
        hash=publicacion.hash,
        link_pago=publicacion.link_pago,
        importe_boleta=cuota.cuota,
        vence=vence,
        iniciado_por_user_id=principal.user.id,
        estado=EstadoPagoSPV.CREADO.value,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.PAGO_SPV_INICIADO,
        actor_user_id=principal.user.id,
        details={
            "pago_spv_id": str(pago_id),
            "id_publicacion": id_publicacion,
            "hash": publicacion.hash,
            "prestamo": prestamo.numero,
            "cuota": cuota.numero,
            "importe": f"{cuota.cuota:.2f}",
            "vence": vence.isoformat(),
        },
    )
    await session.commit()
    return item


# --------------------------------------------------------------------------- registro del pago


def _elegir(item: PagoSupervielle, pagos: list[supervielle.Pago]) -> supervielle.Pago | None:
    """El pago que representa a la publicación: el ya registrado mientras siga hecho; si no, el
    primero hecho; si no hay ninguno, el registrado o el último informado."""
    registrado = next((p for p in pagos if p.id == item.spv_pago_id), None)
    efectivos = [p for p in pagos if p.estado in ESTADOS_SPV_EFECTIVOS]
    if registrado is not None and (registrado.estado in ESTADOS_SPV_EFECTIVOS or not efectivos):
        return registrado
    if efectivos:
        return efectivos[0]
    return pagos[-1] if pagos else None


async def _duplicados(
    session: AsyncSession,
    ctx: RequestContext,
    item: PagoSupervielle,
    elegido: supervielle.Pago,
    pagos: list[supervielle.Pago],
) -> None:
    """Otro pago hecho sobre la misma deuda es un pago doble: Tesorería tiene que verlo (no se
    crea otro comprobante). Se audita una sola vez por pago."""
    for p in pagos:
        if p.id == elegido.id or p.estado not in ESTADOS_SPV_EFECTIVOS:
            continue
        ya = await session.scalar(
            select(func.count()).where(
                AuditSecurityLog.event_type == AuditEvent.PAGO_SPV_DUPLICADO.value,
                AuditSecurityLog.details["spv_pago_id"].astext == p.id,
            )
        )
        if ya:
            continue
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_SPV_DUPLICADO,
            severity=Severity.CRITICAL,
            details={
                "pago_spv_id": str(item.id),
                "spv_pago_id": p.id,
                "spv_pago_id_registrado": elegido.id,
                "importe": f"{p.importe:.2f}" if p.importe is not None else None,
            },
        )


async def registrar(
    session: AsyncSession,
    ctx: RequestContext,
    item: PagoSupervielle,
    pagos: list[supervielle.Pago],
) -> PagoSupervielle:
    """Registra lo que informa el banco de los pagos de una publicación (idempotente)."""
    elegido = _elegir(item, pagos)
    if elegido is None:
        await session.commit()
        return item
    await _duplicados(session, ctx, item, elegido, pagos)
    antes = {"estado": item.estado, "spv_pago_id": item.spv_pago_id}
    estado_anterior = item.estado
    item.estado = elegido.estado.value
    item.spv_pago_id = elegido.id
    item.medio_pago = elegido.medio_pago
    item.importe_pagado = elegido.importe
    item.pagado_en = elegido.fecha.replace(tzinfo=ZONA) if elegido.fecha else None
    item.updated_at = datetime.now(UTC)
    if item.estado == estado_anterior and (
        item.comprobante_id is not None or item.cuota_id is not None
    ):
        await session.commit()
        return item

    detalles: dict[str, object] = {
        "pago_spv_id": str(item.id),
        "spv_pago_id": elegido.id,
        "estado": item.estado,
        "medio_pago": elegido.medio_pago,
        "importe_pagado": f"{elegido.importe:.2f}" if elegido.importe is not None else None,
    }
    boleta: Boleta | None = None
    if item.boleta_id is not None:
        boleta = await session.get(Boleta, item.boleta_id)
        assert boleta is not None  # noqa: S101 - FK RESTRICT
        detalles["boleta"] = boleta.numero
    else:
        detalles.update(await _datos_cuota(session, item))
    efectivo = elegido.estado in ESTADOS_SPV_EFECTIVOS
    if efectivo and boleta is not None and item.comprobante_id is None:
        await _comprobante_para_tesoreria(session, ctx, item, boleta, elegido, detalles)
    elif efectivo and boleta is None and estado_anterior not in EFECTIVOS:
        await _cuota_a_confirmar(session, ctx, item, elegido, detalles)
    elif elegido.estado in ESTADOS_SPV_REVERTIDOS and estado_anterior in EFECTIVOS:
        # TODO(negocio): procedimiento ante un pago reversado o anulado después de aprobado.
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_SPV_REVERTIDO,
            severity=Severity.CRITICAL,
            old_value=antes,
            new_value={"estado": item.estado},
            details=detalles,
        )
    elif item.estado != estado_anterior:
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_SPV_ACTUALIZADO,
            old_value=antes,
            new_value={"estado": item.estado},
            details=detalles,
        )
    await session.commit()
    return item


async def _comprobante_para_tesoreria(
    session: AsyncSession,
    ctx: RequestContext,
    item: PagoSupervielle,
    boleta: Boleta,
    pago: supervielle.Pago,
    detalles: dict[str, object],
) -> None:
    if pago.importe is None:
        # Sin importe informado no se arma el comprobante (nunca se supone el total).
        await _sin_comprobante(session, ctx, pago, {**detalles, "motivo": "importe no informado"})
        return
    coincide = pago.importe == boleta.total_a_pagar
    en_revision = await session.scalar(
        select(Comprobante.id).where(
            Comprobante.boleta_id == boleta.id, Comprobante.estado == PENDIENTE
        )
    )
    if en_revision is not None or boleta.estado != EstadoBoleta.PENDIENTE.value:
        # La boleta ya tiene otro pago en revisión (o ya no está pendiente): el pago queda
        # registrado para que Tesorería lo vea, sin un segundo comprobante.
        await _sin_comprobante(session, ctx, pago, {**detalles, "boleta_estado": boleta.estado})
        return
    fecha = pago.fecha.date() if pago.fecha else today_local()
    comprobante = Comprobante(
        id=uuid.uuid4(),
        boleta_id=boleta.id,
        registro_id=boleta.registro_id,
        periodo=boleta.periodo,
        origen=OrigenComprobante.SUPERVIELLE.value,
        fecha_transferencia=fecha,
        banco_origen=f"Supervielle · {pago.medio_pago}" if pago.medio_pago else "Supervielle",
        numero_operacion=pago.id,
        importe_declarado=pago.importe,
        estado=PENDIENTE,
        subido_por_user_id=item.iniciado_por_user_id,
    )
    session.add(comprobante)
    await session.flush()
    item.comprobante_id = comprobante.id
    await _estimar_comision(session, item, pago, fecha)
    record_audit(
        session,
        ctx,
        AuditEvent.PAGO_SPV_ACREDITADO,
        severity=Severity.INFO if coincide else Severity.WARNING,
        target_user_id=item.iniciado_por_user_id,
        new_value={"estado": PENDIENTE, "origen": OrigenComprobante.SUPERVIELLE.value},
        details={
            **detalles,
            "comprobante_id": str(comprobante.id),
            "importe_coincide": coincide,
            "total_boleta": format_pesos(boleta.total_a_pagar),
        },
    )


async def _estimar_comision(
    session: AsyncSession, item: PagoSupervielle, pago: supervielle.Pago, fecha: date
) -> None:
    """Comisión que absorbe la Caja, estimada con los parámetros vigentes a la fecha del pago;
    guarda las vigencias usadas (regla SNAP). Vacía si falta el importe o algún parámetro."""
    if pago.importe is None:
        return
    estimacion = await comisiones_spv.estimar(session, pago.importe, pago.id_medio, fecha)
    if estimacion is not None:
        item.comision_estimada = estimacion.comision
        item.vigencia_comision_boton_id = estimacion.vigencia_boton_id
        item.vigencia_comision_medio_id = estimacion.vigencia_medio_id
        item.vigencia_comision_iva_id = estimacion.vigencia_iva_id


async def _datos_cuota(session: AsyncSession, item: PagoSupervielle) -> dict[str, object]:
    fila = (
        await session.execute(
            select(Prestamo.numero, CuotaPrestamo.numero, CuotaPrestamo.cuota)
            .join(Prestamo, Prestamo.id == CuotaPrestamo.prestamo_id)
            .where(CuotaPrestamo.id == item.cuota_id)
        )
    ).one()
    return {"prestamo": fila[0], "cuota": fila[1], "importe_cuota": f"{fila[2]:.2f}"}


async def _cuota_a_confirmar(
    session: AsyncSession,
    ctx: RequestContext,
    item: PagoSupervielle,
    pago: supervielle.Pago,
    detalles: dict[str, object],
) -> None:
    """Pago hecho de una cuota: queda a confirmar por Tesorería desde el préstamo."""
    coincide = pago.importe is not None and pago.importe == Decimal(str(detalles["importe_cuota"]))
    fecha = pago.fecha.date() if pago.fecha else today_local()
    await _estimar_comision(session, item, pago, fecha)
    otro_spv = await session.scalar(
        select(func.count()).where(
            PagoSupervielle.cuota_id == item.cuota_id,
            PagoSupervielle.id != item.id,
            PagoSupervielle.estado.in_(EFECTIVOS),
        )
    )
    otro_mp = await session.scalar(
        select(func.count()).where(
            PagoMercadoPago.cuota_id == item.cuota_id,
            PagoMercadoPago.estado == EstadoPagoMP.APPROVED.value,
        )
    )
    otro = bool(otro_spv or otro_mp)
    record_audit(
        session,
        ctx,
        # Dos pagos hechos de la misma cuota: uno sobra y Tesorería tiene que verlo.
        AuditEvent.PAGO_SPV_DUPLICADO if otro else AuditEvent.PAGO_SPV_ACREDITADO,
        severity=Severity.CRITICAL if otro else (Severity.INFO if coincide else Severity.WARNING),
        target_user_id=item.iniciado_por_user_id,
        new_value={"estado": item.estado, "a_confirmar_por": "TESORERIA"},
        details={**detalles, "importe_coincide": coincide},
    )


async def _sin_comprobante(
    session: AsyncSession,
    ctx: RequestContext,
    pago: supervielle.Pago,
    detalles: dict[str, object],
) -> None:
    """Pago hecho que no entra a la mesa: alerta crítica para Tesorería, una vez por pago."""
    ya = await session.scalar(
        select(func.count()).where(
            AuditSecurityLog.event_type == AuditEvent.PAGO_SPV_SIN_COMPROBANTE.value,
            AuditSecurityLog.details["spv_pago_id"].astext == pago.id,
        )
    )
    if not ya:
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_SPV_SIN_COMPROBANTE,
            severity=Severity.CRITICAL,
            details=detalles,
        )


async def _consultar_y_registrar(
    session: AsyncSession, ctx: RequestContext, item: PagoSupervielle
) -> PagoSupervielle:
    try:
        pagos = await supervielle.pagos_de(item.hash)
    except supervielle.SupervielleError as exc:
        raise _no_disponible() from exc
    bloqueado = await session.get(PagoSupervielle, item.id, with_for_update=True)
    assert bloqueado is not None  # noqa: S101 - recién leído
    return await registrar(session, ctx, bloqueado, pagos)


async def refrescar_antes_de_aprobar(
    session: AsyncSession, ctx: RequestContext, comprobante_id: uuid.UUID
) -> None:
    """Antes de que Tesorería apruebe un comprobante de Supervielle, se vuelve a consultar el pago
    al banco: una reversión cuyo aviso todavía no llegó tiene que bloquear la aprobación. Si el
    banco no responde, no se aprueba (503)."""
    item = await de_comprobante(session, comprobante_id)
    if item is None:
        return
    if not supervielle.configurado():
        raise _no_disponible()
    await _consultar_y_registrar(session, ctx, item)


async def sincronizar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, pago_spv_id: uuid.UUID
) -> PagoSupervielle:
    """«Ya pagué»: consulta la publicación al banco y registra sus pagos."""
    item = await session.get(PagoSupervielle, pago_spv_id)
    if item is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El pago no existe.")
    # Solo quien puede ver la boleta o el préstamo (el mismo control que para verlos).
    await _exigir_acceso(session, principal, item)
    await session.commit()
    if not supervielle.configurado():
        raise _no_disponible()
    return await _consultar_y_registrar(session, ctx, item)


class AvisoInvalidoError(Exception):
    """El aviso no corresponde a una deuda publicada por la Suite."""


async def aviso(session: AsyncSession, ctx: RequestContext, hash_: str) -> None:
    """Aviso de pago del banco (sin sesión ni firma). Solo dispara la consulta a la API: el
    hash tiene que ser de una deuda publicada por la Suite y el pago se toma del banco."""
    item = (
        await session.scalar(select(PagoSupervielle).where(PagoSupervielle.hash == hash_))
        if supervielle.hash_valido(hash_)
        else None
    )
    if item is None:
        # Solo al log (no a la auditoría): cualquiera puede llamar a esta dirección, y una fila
        # por aviso inventado llenaría la auditoría.
        logger.warning(
            "Aviso de Supervielle con un hash desconocido",
            extra={"ip": ctx.ip_address, "hash": hash_[:100]},
        )
        raise AvisoInvalidoError
    if not supervielle.configurado():
        # Sin 200 el banco reintenta más tarde.
        raise _no_disponible()
    bloqueado = await session.get(PagoSupervielle, item.id, with_for_update=True)
    assert bloqueado is not None  # noqa: S101 - recién leído
    ahora = datetime.now(UTC)
    if bloqueado.consultado_en is not None and ahora - bloqueado.consultado_en < PAUSA_AVISO:
        await _marcar_pendiente(session, item.id)
        return
    bloqueado.consultado_en = ahora
    generacion = bloqueado.aviso_generacion
    await session.commit()
    try:
        await _consultar_y_registrar(session, ctx, bloqueado)
    except ProblemError:
        # El banco no contestó: se responde 503 (el banco reintenta) y además queda pendiente.
        await session.rollback()
        await _marcar_pendiente(session, item.id)
        raise
    # Consultado ahora: los avisos anteriores a esta consulta ya quedaron cubiertos.
    await _limpiar_pendiente(session, item.id, generacion)


async def _marcar_pendiente(session: AsyncSession, pago_id: uuid.UUID) -> None:
    """Un aviso más sin consultar: sube la generación y conserva la hora del más viejo (quien
    llame a la dirección del aviso no puede correr esa hora hacia adelante)."""
    await session.execute(
        update(PagoSupervielle)
        .where(PagoSupervielle.id == pago_id)
        .values(
            aviso_generacion=PagoSupervielle.aviso_generacion + 1,
            aviso_pendiente_en=func.coalesce(PagoSupervielle.aviso_pendiente_en, func.now()),
        )
    )
    await session.commit()


async def _limpiar_pendiente(session: AsyncSession, pago_id: uuid.UUID, generacion: int) -> None:
    """Borra la marca solo si no llegó otro aviso desde que se leyó `generacion`."""
    await session.execute(
        update(PagoSupervielle)
        .where(PagoSupervielle.id == pago_id, PagoSupervielle.aviso_generacion == generacion)
        .values(aviso_pendiente_en=None)
    )
    await session.commit()


# Tope por vuelta del procesamiento programado (cada 2 minutos): cantidad de publicaciones y
# tiempo total. Se toman primero las que hace más tiempo no se consultan, así una publicación que
# falla siempre no frena a las demás. Una marca no se descarta nunca: si sigue pendiente después
# de un día, se avisa a Tesorería (auditoría crítica) y la conciliación diaria también la revisa.
AVISOS_POR_VUELTA = 50
TIEMPO_POR_VUELTA = timedelta(seconds=90)
AVISO_DEMORADO = timedelta(days=1)


async def procesar_avisos_pendientes(session: AsyncSession, ctx: RequestContext) -> int:
    """Consulta al banco las publicaciones con un aviso pendiente. La marca se borra solo si no
    llegó otro aviso mientras se consultaba; si el banco falla, queda para la próxima vuelta.
    Devuelve cuántas se consultaron."""
    if not supervielle.configurado():
        return 0
    inicio = datetime.now(UTC)
    await _alertar_demorados(session, ctx, inicio)
    ids = (
        await session.scalars(
            select(PagoSupervielle.id)
            .where(PagoSupervielle.aviso_pendiente_en.is_not(None))
            .order_by(PagoSupervielle.consultado_en.asc().nulls_first())
            .limit(AVISOS_POR_VUELTA)
        )
    ).all()
    await session.commit()
    consultadas = 0
    for pago_id in ids:
        if datetime.now(UTC) - inicio > TIEMPO_POR_VUELTA:
            break
        item = await session.get(PagoSupervielle, pago_id, with_for_update=True)
        assert item is not None  # noqa: S101 - sin borrado
        ahora = datetime.now(UTC)
        if item.aviso_pendiente_en is None or (
            item.consultado_en is not None and ahora - item.consultado_en < PAUSA_AVISO
        ):
            await session.commit()
            continue
        item.consultado_en = ahora
        generacion = item.aviso_generacion
        await session.commit()
        try:
            await _consultar_y_registrar(session, ctx, item)
        except ProblemError:
            await session.rollback()
            continue
        consultadas += 1
        await _limpiar_pendiente(session, pago_id, generacion)
    return consultadas


async def _alertar_demorados(session: AsyncSession, ctx: RequestContext, ahora: datetime) -> None:
    """Auditoría crítica (una vez por marca) de los avisos que llevan un día sin consultarse.
    Acotada por vuelta; la fila recuerda cuándo se alertó, así no se repite."""
    demorados = (
        await session.scalars(
            select(PagoSupervielle)
            .where(
                PagoSupervielle.aviso_pendiente_en < ahora - AVISO_DEMORADO,
                or_(
                    PagoSupervielle.aviso_alertado_en.is_(None),
                    PagoSupervielle.aviso_alertado_en < PagoSupervielle.aviso_pendiente_en,
                ),
            )
            .order_by(PagoSupervielle.aviso_pendiente_en)
            .limit(AVISOS_POR_VUELTA)
            .with_for_update()
        )
    ).all()
    for item in demorados:
        record_audit(
            session,
            ctx,
            AuditEvent.PAGO_SPV_AVISO_DEMORADO,
            severity=Severity.CRITICAL,
            details={
                "pago_spv_id": str(item.id),
                "id_publicacion": item.id_publicacion,
                "pendiente_desde": item.aviso_pendiente_en.isoformat()
                if item.aviso_pendiente_en
                else None,
            },
        )
        item.aviso_alertado_en = ahora
    await session.commit()


# --------------------------------------------------------------------------- conciliación


# Una deuda vencida hace más de estos días ya no se consulta en la conciliación diaria (un pago en
# caja o por DEBIN puede acreditarse unos días después).
DIAS_ABIERTAS = 10
# Avisos sin consultar que también revisa la conciliación, y topes de cada corrida (el cron la
# corta a los 30 minutos).
DIAS_ABIERTAS_AVISO = 7
CONSULTAS_POR_CONCILIACION = 200
TIEMPO_POR_CONCILIACION = timedelta(minutes=20)
ABIERTOS = (
    EstadoPagoSPV.CREADO.value,
    EstadoPagoSPV.PENDIENTE.value,
    EstadoPagoSPV.APROBADO.value,
)


@dataclass
class ResultadoConciliacion:
    consultadas: int = 0
    # (id_publicacion, estado anterior, estado nuevo)
    actualizadas: list[tuple[int, str, str]] = field(default_factory=list)
    # Pagos de la rendición de publicaciones que no armó la Suite: (hash, id de pago, importe).
    ajenos: list[tuple[str, str, str]] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)


async def conciliar(
    session: AsyncSession, ctx: RequestContext, desde: date, hasta: date
) -> ResultadoConciliacion:
    """Recupera los pagos cuyo aviso se perdió (el banco descarta el aviso cuando agota los
    reintentos): consulta las deudas abiertas de la Suite y las que figuran en la rendición del
    banco entre `desde` y `hasta`, y las registra como si hubiera llegado el aviso."""
    if not supervielle.configurado():
        raise _no_disponible()
    resultado = ResultadoConciliacion()
    try:
        rendidos = await supervielle.rendicion_pagos(desde, hasta)
    except supervielle.SupervielleError as exc:
        resultado.errores.append(f"rendición: {exc}")
        rendidos = []
    hashes = {r.hash_publicacion for r in rendidos}
    propias = (
        await session.scalars(select(PagoSupervielle).where(PagoSupervielle.hash.in_(hashes)))
    ).all()
    conocidos = {p.hash for p in propias}
    resultado.ajenos = [
        (r.hash_publicacion, r.pago.id, f"{r.pago.importe:.2f}" if r.pago.importe else "")
        for r in rendidos
        if r.hash_publicacion not in conocidos
    ]
    abiertas = (
        await session.scalars(
            select(PagoSupervielle)
            .where(
                or_(
                    and_(
                        PagoSupervielle.estado.in_(ABIERTOS),
                        PagoSupervielle.vence >= today_local() - timedelta(days=DIAS_ABIERTAS),
                    ),
                    # Un aviso reciente que no se pudo consultar se revisa sea cual sea su estado.
                    PagoSupervielle.aviso_pendiente_en
                    >= datetime.now(UTC) - timedelta(days=DIAS_ABIERTAS_AVISO),
                ),
            )
            .order_by(PagoSupervielle.vence.desc())
            .limit(CONSULTAS_POR_CONCILIACION)
        )
    ).all()
    # Primero las que figuran en la rendición (hay un pago informado); después las abiertas.
    a_consultar = {p.id: (p.id_publicacion, p.estado) for p in [*propias, *abiertas]}
    await session.commit()
    inicio = datetime.now(UTC)
    for n, (pago_id, (id_publicacion, antes)) in enumerate(a_consultar.items()):
        if n >= CONSULTAS_POR_CONCILIACION or datetime.now(UTC) - inicio > TIEMPO_POR_CONCILIACION:
            resultado.errores.append(
                f"quedaron {len(a_consultar) - n} publicaciones sin consultar (tope de la corrida)"
            )
            break
        resultado.consultadas += 1
        item = await session.get(PagoSupervielle, pago_id)
        assert item is not None  # noqa: S101 - sin borrado
        try:
            actualizado = await _consultar_y_registrar(session, ctx, item)
        except ProblemError:
            await session.rollback()
            resultado.errores.append(f"publicación {id_publicacion}: el banco no respondió")
            continue
        if actualizado.estado != antes:
            resultado.actualizadas.append((id_publicacion, antes, actualizado.estado))
    return resultado


async def confirmar_cuota(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    prestamo_id: uuid.UUID,
    pago_spv_id: uuid.UUID,
) -> Prestamo:
    """Tesorería confirma el pago de una cuota. Antes se vuelve a consultar el pago al banco: una
    reversión cuyo aviso todavía no llegó tiene que bloquear la confirmación. Si el banco no
    responde, no se confirma (503)."""
    await prestamos_service.get_prestamo(session, principal, prestamo_id)
    item = await session.get(PagoSupervielle, pago_spv_id)
    es_del_prestamo = (
        item is not None
        and item.cuota_id is not None
        and (
            await session.scalar(
                select(CuotaPrestamo.prestamo_id).where(CuotaPrestamo.id == item.cuota_id)
            )
            == prestamo_id
        )
    )
    await session.commit()
    if item is not None and es_del_prestamo and item.confirmado_en is None:
        if not supervielle.configurado():
            raise _no_disponible(CUOTA_POR_TESORERIA)
        await _consultar_y_registrar(session, ctx, item)
    return await prestamos_service.confirmar_cobro_spv(
        session, ctx, principal, prestamo_id, pago_spv_id
    )


# --------------------------------------------------------------------------- consulta


async def _exigir_acceso(
    session: AsyncSession, principal: Principal, item: PagoSupervielle
) -> None:
    if item.boleta_id is not None:
        await ddjj_service.get_boleta(session, principal, item.boleta_id)
        return
    prestamo_id = await session.scalar(
        select(CuotaPrestamo.prestamo_id).where(CuotaPrestamo.id == item.cuota_id)
    )
    assert prestamo_id is not None  # noqa: S101 - FK RESTRICT
    prestamo = await prestamos_service.get_prestamo(session, principal, prestamo_id)
    # Los pagos de la cuota son del titular: el garante ve el préstamo, no sus pagos.
    if not prestamos_service.ve_todo(principal):
        propio = await prestamos_service.escribano_de(session, principal.user)
        if propio is None or propio.id != prestamo.escribano_id:
            raise ProblemError(HTTPStatus.NOT_FOUND, "El pago no existe.")


async def cuotas_cobradas(
    session: AsyncSession, pagos: list[PagoSupervielle]
) -> dict[uuid.UUID, CuotaCobradaOut]:
    """La cuota de cada deuda de préstamo, por id de la deuda (las de boletas no figuran)."""
    ids = {p.cuota_id for p in pagos if p.cuota_id is not None}
    if not ids:
        return {}
    filas = (
        await session.execute(
            select(CuotaPrestamo.id, CuotaPrestamo.numero, Prestamo.id, Prestamo.numero)
            .join(Prestamo, Prestamo.id == CuotaPrestamo.prestamo_id)
            .where(CuotaPrestamo.id.in_(ids))
        )
    ).all()
    por_cuota = {
        f[0]: CuotaCobradaOut(prestamo_id=f[2], prestamo_numero=f[3], numero=f[1]) for f in filas
    }
    return {p.id: por_cuota[p.cuota_id] for p in pagos if p.cuota_id in por_cuota}


async def de_prestamo(session: AsyncSession, prestamo_id: uuid.UUID) -> list[PagoSupervielle]:
    """Deudas publicadas de las cuotas de un préstamo (el acceso ya se controló)."""
    resultado = await session.scalars(
        select(PagoSupervielle)
        .join(CuotaPrestamo, CuotaPrestamo.id == PagoSupervielle.cuota_id)
        .where(CuotaPrestamo.prestamo_id == prestamo_id)
        .order_by(PagoSupervielle.created_at.desc())
    )
    return list(resultado.all())


async def de_boleta(
    session: AsyncSession, principal: Principal, boleta_id: uuid.UUID
) -> list[PagoSupervielle]:
    await ddjj_service.get_boleta(session, principal, boleta_id)
    resultado = await session.scalars(
        select(PagoSupervielle)
        .where(PagoSupervielle.boleta_id == boleta_id)
        .order_by(PagoSupervielle.created_at.desc())
    )
    return list(resultado.all())


async def de_comprobante(
    session: AsyncSession, comprobante_id: uuid.UUID
) -> PagoSupervielle | None:
    return await session.scalar(
        select(PagoSupervielle).where(PagoSupervielle.comprobante_id == comprobante_id)
    )


async def registro(
    session: AsyncSession, page: PageParams, *, solo_informados: bool = True
) -> tuple[list[PagoSupervielle], int]:
    """Registro de pagos con el botón Supervielle para Tesorería (los más recientes primero)."""
    stmt = select(PagoSupervielle)
    if solo_informados:
        stmt = stmt.where(PagoSupervielle.spv_pago_id.is_not(None))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    filas = await session.scalars(
        stmt.order_by(PagoSupervielle.updated_at.desc()).offset(page.offset).limit(page.page_size)
    )
    return list(filas.all()), int(total or 0)
