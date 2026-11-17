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

Todo cambio de estado queda en la auditoría.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
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
    EstadoPagoSPV,
    OrigenComprobante,
)
from app.modules.pagos.models import SECUENCIA_PUBLICACION_SPV, Comprobante, PagoSupervielle

ZONA = ZoneInfo("America/Argentina/San_Juan")
logger = logging.getLogger(__name__)
# A lo sumo una consulta al banco por publicación en este lapso (por proceso), venga de donde
# venga el aviso. Un aviso repetido dentro de la pausa no se descarta: se responde 200 y la
# consulta queda programada para cuando termine la pausa (una sola por publicación). Así nadie
# puede multiplicar los pedidos a la API ni frenar los avisos del banco. Las claves son hashes de
# publicaciones de la Suite (los desconocidos se rechazan antes): no crecen con lo que se reciba.
PAUSA_AVISO_NS = 15 * 1_000_000_000
_ultima_consulta: dict[str, int] = {}
_diferidas: dict[str, asyncio.Task[None]] = {}
PENDIENTE = EstadoComprobante.PENDIENTE_REVISION.value
EFECTIVOS = {e.value for e in ESTADOS_SPV_EFECTIVOS}


def _no_disponible() -> ProblemError:
    return ProblemError(
        HTTPStatus.SERVICE_UNAVAILABLE,
        "El botón de pagos Supervielle no está disponible en este momento: probá más tarde o "
        "pagá por transferencia y adjuntá el comprobante.",
    )


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
    if item.estado == estado_anterior and item.comprobante_id is not None:
        await session.commit()
        return item

    boleta = await session.get(Boleta, item.boleta_id)
    assert boleta is not None  # noqa: S101 - FK RESTRICT
    detalles: dict[str, object] = {
        "pago_spv_id": str(item.id),
        "spv_pago_id": elegido.id,
        "estado": item.estado,
        "medio_pago": elegido.medio_pago,
        "importe_pagado": f"{elegido.importe:.2f}" if elegido.importe is not None else None,
        "boleta": boleta.numero,
    }
    if elegido.estado in ESTADOS_SPV_EFECTIVOS and item.comprobante_id is None:
        await _comprobante_para_tesoreria(session, ctx, item, boleta, elegido, detalles)
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
    if pago.importe is not None:
        estimacion = await comisiones_spv.estimar(session, pago.importe, pago.id_medio, fecha)
        if estimacion is not None:
            item.comision_estimada = estimacion.comision
            item.vigencia_comision_boton_id = estimacion.vigencia_boton_id
            item.vigencia_comision_medio_id = estimacion.vigencia_medio_id
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
    # Solo quien puede ver la boleta (el mismo control que para verla).
    await ddjj_service.get_boleta(session, principal, item.boleta_id)
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
    ahora = time.monotonic_ns()
    transcurrido = ahora - _ultima_consulta.get(item.hash, -PAUSA_AVISO_NS)
    if transcurrido < PAUSA_AVISO_NS:
        if item.hash not in _diferidas:
            espera_ms = (PAUSA_AVISO_NS - transcurrido) // 1_000_000 + 1
            _diferidas[item.hash] = asyncio.create_task(
                _consulta_diferida(item.id, item.hash, espera_ms, ctx)
            )
        return
    _ultima_consulta[item.hash] = ahora
    try:
        await _consultar_y_registrar(session, ctx, item)
    except ProblemError:
        # Si el banco no contestó, se responde 503 y el reintento del banco vuelve a consultar.
        _ultima_consulta.pop(item.hash, None)
        raise


def _abrir_sesion() -> AsyncSession:
    from app.core.db import get_sessionmaker

    return get_sessionmaker()()


async def _consulta_diferida(
    pago_id: uuid.UUID, hash_: str, espera_ms: int, ctx: RequestContext
) -> None:
    """La consulta de un aviso que llegó durante la pausa. Si falla, la recupera la conciliación
    programada (deploy/instalar-cron.sh)."""
    try:
        await asyncio.sleep(espera_ms / 1000)
        _ultima_consulta[hash_] = time.monotonic_ns()
        async with _abrir_sesion() as session:
            item = await session.get(PagoSupervielle, pago_id)
            if item is not None:
                await _consultar_y_registrar(session, ctx, item)
    except Exception:
        logger.exception("Falló la consulta diferida de un aviso de Supervielle")
    finally:
        _diferidas.pop(hash_, None)


# --------------------------------------------------------------------------- conciliación


# Una deuda vencida hace más de estos días ya no se consulta en la conciliación diaria (un pago en
# caja o por DEBIN puede acreditarse unos días después).
DIAS_ABIERTAS = 10
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
            select(PagoSupervielle).where(
                PagoSupervielle.estado.in_(ABIERTOS),
                PagoSupervielle.vence >= today_local() - timedelta(days=DIAS_ABIERTAS),
            )
        )
    ).all()
    a_consultar = {p.id: (p.id_publicacion, p.estado) for p in [*abiertas, *propias]}
    await session.commit()
    for pago_id, (id_publicacion, antes) in a_consultar.items():
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


# --------------------------------------------------------------------------- consulta


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
