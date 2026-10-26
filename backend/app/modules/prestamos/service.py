"""Préstamos a afiliados (Módulo 9).

Reglas (los valores concretos —tasas, plazos, topes— son parámetros de cada línea):
- Tope de afectación: la cuota más alta del plan más las cuotas de los otros préstamos vigentes
  del escribano no pueden superar el porcentaje de su ingreso neto mensual fijado por la línea.
- Garante (regla inquebrantable): matrícula activa y sin préstamos propios en mora, sin ser
  garante de un préstamo con cuotas vencidas impagas y sin deuda de aportes con la Caja.
- Quien carga la solicitud no la resuelve (cuatro ojos). Al otorgar se reevalúa todo con los
  datos del día y se genera el plan de cuotas, inmutable.
- Las cuotas se cobran en orden. TODO(negocio): interés punitorio por pago fuera de término.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.money import format_pesos
from app.core.errors import ProblemError
from app.modules.ddjj.catalog import EstadoBoleta
from app.modules.ddjj.models import Boleta
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.iam.models import User
from app.modules.migracion.catalog import EstadoBoletaHistorica
from app.modules.migracion.models import HistoricoBoleta
from app.modules.padron.catalog import EstadoMatricula
from app.modules.padron.models import Adscripcion, Escribano
from app.modules.prestamos import motor
from app.modules.prestamos.catalog import EstadoCuota, EstadoPrestamo, Sistema
from app.modules.prestamos.models import CuotaPrestamo, Linea, Prestamo
from app.modules.prestamos.schemas import LineaIn, SolicitudIn

CERO = Decimal("0.00")
# Matrículas que pueden tomar un préstamo. TODO(negocio): confirmar si JUBILADO solo accede a la
# línea de pasivos y si un SUSPENDIDO puede solicitar.
ESTADOS_TOMADOR = frozenset({EstadoMatricula.ACTIVO.value, EstadoMatricula.JUBILADO.value})
VIGENTE = EstadoPrestamo.OTORGADO.value
PENDIENTE = EstadoCuota.PENDIENTE.value


def _not_found(what: str) -> ProblemError:
    return ProblemError(HTTPStatus.NOT_FOUND, f"{what} no existe.")


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _invalid(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, message)


# --------------------------------------------------------------------------- líneas

LINEA_CAMPOS = (
    "codigo",
    "nombre",
    "descripcion",
    "sistema",
    "plazo_minimo",
    "plazo_maximo",
    "monto_minimo",
    "monto_maximo",
    "tna",
    "afectacion_maxima",
    "requiere_garante",
    "es_ejemplo",
    "is_active",
)


def porcentaje(valor: Decimal) -> str:
    """30.0000 -> "30 %"; 35.54 -> "35,54 %" (para mensajes)."""
    texto = f"{valor:.4f}".rstrip("0").rstrip(".")
    return f"{texto.replace('.', ',')} %"


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return f"{valor:.4f}" if valor.as_tuple().exponent == -4 else f"{valor:.2f}"
    if isinstance(valor, date | uuid.UUID):
        return str(valor)
    return valor


def _valores(obj: object, campos: tuple[str, ...]) -> dict[str, Any]:
    return {c: _json(getattr(obj, c)) for c in campos}


async def list_lineas(session: AsyncSession, *, solo_activas: bool) -> list[Linea]:
    stmt = select(Linea).order_by(Linea.nombre)
    if solo_activas:
        stmt = stmt.where(Linea.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def get_linea(session: AsyncSession, linea_id: uuid.UUID) -> Linea:
    linea = await session.get(Linea, linea_id)
    if linea is None:
        raise _not_found("La línea de crédito")
    return linea


async def guardar_linea(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    data: LineaIn,
    linea_id: uuid.UUID | None = None,
) -> Linea:
    """Alta o edición. Los préstamos ya solicitados conservan sus condiciones (SNAP)."""
    valores = data.model_dump()
    valores["sistema"] = data.sistema.value
    if linea_id is None:
        if await session.scalar(select(Linea.id).where(Linea.codigo == data.codigo)):
            raise _conflict("Ya hay una línea con ese código.")
        linea = Linea(id=uuid.uuid4(), **valores, created_by_user_id=actor.id)
        session.add(linea)
        record_audit(
            session,
            ctx,
            AuditEvent.PRESTAMO_LINEA_CREADA,
            severity=Severity.WARNING,
            actor_user_id=actor.id,
            new_value=_valores(linea, LINEA_CAMPOS),
            details={"linea_id": str(linea.id)},
        )
    else:
        existente = await session.get(Linea, linea_id, with_for_update=True)
        if existente is None:
            raise _not_found("La línea de crédito")
        linea = existente
        if data.codigo != linea.codigo:
            raise _conflict("El código de una línea no cambia.")
        antes = _valores(linea, LINEA_CAMPOS)
        for campo, valor in valores.items():
            setattr(linea, campo, valor)
        despues = _valores(linea, LINEA_CAMPOS)
        cambios = [c for c in LINEA_CAMPOS if antes[c] != despues[c]]
        if cambios:
            record_audit(
                session,
                ctx,
                AuditEvent.PRESTAMO_LINEA_ACTUALIZADA,
                severity=Severity.WARNING,
                actor_user_id=actor.id,
                old_value={c: antes[c] for c in cambios},
                new_value={c: despues[c] for c in cambios},
                details={"linea_id": str(linea.id), "codigo": linea.codigo},
            )
    await session.commit()
    await session.refresh(linea)
    return linea


# --------------------------------------------------------------------------- situación


async def escribano_de(session: AsyncSession, user: User) -> Escribano | None:
    return await session.scalar(select(Escribano).where(Escribano.user_id == user.id))


async def get_escribano(session: AsyncSession, escribano_id: uuid.UUID) -> Escribano:
    escribano = await session.get(Escribano, escribano_id)
    if escribano is None:
        raise _not_found("El escribano")
    return escribano


async def compromiso_vigente(
    session: AsyncSession, escribano_id: uuid.UUID, *, excluir: uuid.UUID | None = None
) -> Decimal:
    """Suma de la próxima cuota impaga de cada préstamo vigente del escribano."""
    proxima = (
        select(CuotaPrestamo.prestamo_id, func.min(CuotaPrestamo.numero).label("numero"))
        .where(CuotaPrestamo.estado == PENDIENTE)
        .group_by(CuotaPrestamo.prestamo_id)
        .subquery()
    )
    stmt = (
        select(func.coalesce(func.sum(CuotaPrestamo.cuota), 0))
        .join(
            proxima,
            and_(
                proxima.c.prestamo_id == CuotaPrestamo.prestamo_id,
                proxima.c.numero == CuotaPrestamo.numero,
            ),
        )
        .join(Prestamo, Prestamo.id == CuotaPrestamo.prestamo_id)
        .where(Prestamo.escribano_id == escribano_id, Prestamo.estado == VIGENTE)
    )
    if excluir is not None:
        stmt = stmt.where(Prestamo.id != excluir)
    return Decimal(await session.scalar(stmt) or 0).quantize(Decimal("0.01"))


def _cuotas_vencidas(hoy: date) -> Any:
    return and_(CuotaPrestamo.estado == PENDIENTE, CuotaPrestamo.vencimiento < hoy)


async def en_mora(session: AsyncSession, escribano_id: uuid.UUID, hoy: date) -> bool:
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(CuotaPrestamo)
            .join(Prestamo, Prestamo.id == CuotaPrestamo.prestamo_id)
            .where(Prestamo.escribano_id == escribano_id, _cuotas_vencidas(hoy))
        )
    )


async def garantiza_en_mora(session: AsyncSession, escribano_id: uuid.UUID, hoy: date) -> bool:
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(CuotaPrestamo)
            .join(Prestamo, Prestamo.id == CuotaPrestamo.prestamo_id)
            .where(Prestamo.garante_escribano_id == escribano_id, _cuotas_vencidas(hoy))
        )
    )


async def deuda_aportes(session: AsyncSession, escribano_id: uuid.UUID, hoy: date) -> bool:
    """Boletas impagas y vencidas de los registros donde el escribano tiene cargo vigente,
    incluidas las del sistema anterior (histórico migrado)."""
    registros = select(Adscripcion.registro_id).where(
        Adscripcion.escribano_id == escribano_id, Adscripcion.is_current.is_(True)
    )
    actuales = await session.scalar(
        select(func.count()).where(
            Boleta.registro_id.in_(registros),
            Boleta.estado == EstadoBoleta.PENDIENTE.value,
            Boleta.fecha_vencimiento < hoy,
        )
    )
    if actuales:
        return True
    historicas = await session.scalar(
        select(func.count()).where(
            HistoricoBoleta.registro_id.in_(registros),
            HistoricoBoleta.estado == EstadoBoletaHistorica.IMPAGA.value,
            HistoricoBoleta.fecha_vencimiento < hoy,
        )
    )
    return bool(historicas)


async def inhabilidades_garante(session: AsyncSession, garante: Escribano, hoy: date) -> list[str]:
    motivos = []
    if garante.estado_matricula != EstadoMatricula.ACTIVO.value:
        motivos.append("El garante no tiene la matrícula activa.")
    if await en_mora(session, garante.id, hoy):
        motivos.append("El garante tiene préstamos propios con cuotas vencidas impagas.")
    if await garantiza_en_mora(session, garante.id, hoy):
        motivos.append("El garante ya garantiza un préstamo con cuotas vencidas impagas.")
    if await deuda_aportes(session, garante.id, hoy):
        motivos.append("El garante registra deuda de aportes previsionales con la Caja.")
    return motivos


# --------------------------------------------------------------------------- evaluación


GARANTE_NO_HABIL = "El garante propuesto no reúne las condiciones exigidas: consultá con la Caja."


@dataclass
class Evaluacion:
    sistema: Sistema
    tna: Decimal
    tasa_es_ejemplo: bool
    capital: Decimal
    cuotas: int
    plan: list[motor.Cuota]
    cuota_maxima: Decimal
    otras_cuotas: Decimal
    afectacion: Decimal | None
    afectacion_maxima: Decimal
    requiere_garante: bool
    impedimentos: list[str] = field(default_factory=list)
    # Subconjunto de `impedimentos` que describe la situación del garante (un tercero).
    impedimentos_garante: list[str] = field(default_factory=list)

    def impedimentos_para_titular(self) -> list[str]:
        """Lo que puede ver el titular: los motivos del garante sin revelar su situación."""
        propios = [i for i in self.impedimentos if i not in self.impedimentos_garante]
        return propios + ([GARANTE_NO_HABIL] if self.impedimentos_garante else [])


async def evaluar(
    session: AsyncSession,
    linea: Linea,
    *,
    capital: Decimal,
    cuotas: int,
    hoy: date,
    escribano: Escribano | None,
    ingreso_neto: Decimal | None,
    garante_id: uuid.UUID | None,
    excluir: uuid.UUID | None = None,
    condiciones: tuple[Sistema, Decimal, bool] | None = None,
) -> Evaluacion:
    """Plan y reglas de otorgamiento. `condiciones` fija sistema y tasa ya pactados (SNAP)."""
    sistema, tna, ejemplo = condiciones or (Sistema(linea.sistema), linea.tna, linea.es_ejemplo)
    impedimentos: list[str] = []
    del_garante: list[str] = []
    if not linea.is_active and condiciones is None:
        impedimentos.append("La línea de crédito no está habilitada.")
    if not linea.monto_minimo <= capital <= linea.monto_maximo:
        impedimentos.append(
            f"El monto tiene que estar entre {format_pesos(linea.monto_minimo)} y "
            f"{format_pesos(linea.monto_maximo)}."
        )
    if not linea.plazo_minimo <= cuotas <= linea.plazo_maximo:
        impedimentos.append(
            f"El plazo tiene que estar entre {linea.plazo_minimo} y {linea.plazo_maximo} cuotas."
        )
    try:
        plan = motor.plan(sistema, capital, tna, cuotas, motor.sumar_meses(hoy, 1))
    except motor.MotorPrestamoError as exc:
        raise _invalid(str(exc)) from exc
    cuota_maxima = motor.cuota_maxima(plan)
    otras = CERO
    afectacion: Decimal | None = None
    if escribano is not None:
        if escribano.estado_matricula not in ESTADOS_TOMADOR:
            impedimentos.append("La matrícula del solicitante no le permite tomar préstamos.")
        if await en_mora(session, escribano.id, hoy):
            impedimentos.append("El solicitante tiene cuotas de préstamos vencidas impagas.")
        otras = await compromiso_vigente(session, escribano.id, excluir=excluir)
    if ingreso_neto is not None:
        afectacion = motor.afectacion(cuota_maxima + otras, ingreso_neto)
        if afectacion > linea.afectacion_maxima:
            impedimentos.append(
                f"La cuota compromete el {porcentaje(afectacion)} del ingreso neto (con otros "
                f"préstamos): el tope de la línea es {porcentaje(linea.afectacion_maxima)}."
            )
    if garante_id is not None:
        if escribano is not None and garante_id == escribano.id:
            impedimentos.append("El solicitante no puede ser su propio garante.")
        else:
            del_garante = await inhabilidades_garante(
                session, await get_escribano(session, garante_id), hoy
            )
            impedimentos += del_garante
    elif linea.requiere_garante:
        impedimentos.append("La línea exige un garante solidario matriculado.")
    return Evaluacion(
        sistema=sistema,
        tna=tna,
        tasa_es_ejemplo=ejemplo,
        capital=capital,
        cuotas=cuotas,
        plan=plan,
        cuota_maxima=cuota_maxima,
        otras_cuotas=otras,
        afectacion=afectacion,
        afectacion_maxima=linea.afectacion_maxima,
        requiere_garante=linea.requiere_garante,
        impedimentos=impedimentos,
        impedimentos_garante=del_garante,
    )


def _rechazar_si_hay(impedimentos: list[str], *, status: HTTPStatus) -> None:
    if impedimentos:
        raise ProblemError(
            status,
            " ".join(impedimentos),
            type_="urn:suite-notarial:prestamos:impedimentos",
            extra={"impedimentos": impedimentos},
        )


# --------------------------------------------------------------------------- solicitudes


def ve_todo(principal: Principal) -> bool:
    return Perm.PRESTAMOS_READ_ALL.value in principal.permissions


async def crear_solicitud(
    session: AsyncSession, ctx: RequestContext, actor: User, data: SolicitudIn
) -> Prestamo:
    linea = await get_linea(session, data.linea_id)
    escribano = await get_escribano(session, data.escribano_id)
    ev = await evaluar(
        session,
        linea,
        capital=data.capital,
        cuotas=data.cuotas,
        hoy=today_local(),
        escribano=escribano,
        ingreso_neto=data.ingreso_neto,
        garante_id=data.garante_escribano_id,
    )
    _rechazar_si_hay(ev.impedimentos, status=HTTPStatus.UNPROCESSABLE_ENTITY)
    assert ev.afectacion is not None  # noqa: S101 - hay ingreso neto
    prestamo = Prestamo(
        id=uuid.uuid4(),
        escribano_id=escribano.id,
        linea_id=linea.id,
        garante_escribano_id=data.garante_escribano_id,
        estado=EstadoPrestamo.SOLICITADO.value,
        sistema=ev.sistema.value,
        tna=ev.tna,
        capital=ev.capital,
        cuotas=ev.cuotas,
        tasa_es_ejemplo=ev.tasa_es_ejemplo,
        ingreso_neto=data.ingreso_neto,
        otras_cuotas=ev.otras_cuotas,
        cuota_maxima=ev.cuota_maxima,
        afectacion=ev.afectacion,
        afectacion_maxima=ev.afectacion_maxima,
        observaciones=data.observaciones,
        creado_por_user_id=actor.id,
    )
    session.add(prestamo)
    record_audit(
        session,
        ctx,
        AuditEvent.PRESTAMO_SOLICITADO,
        actor_user_id=actor.id,
        new_value={
            "linea": linea.codigo,
            "capital": f"{ev.capital:.2f}",
            "cuotas": ev.cuotas,
            "tna": f"{ev.tna:.4f}",
            "afectacion": f"{ev.afectacion:.2f}",
            "garante": str(data.garante_escribano_id) if data.garante_escribano_id else None,
        },
        details={"prestamo_id": str(prestamo.id), "escribano_id": str(escribano.id)},
    )
    await session.commit()
    await session.refresh(prestamo)
    return prestamo


async def get_prestamo(
    session: AsyncSession, principal: Principal, prestamo_id: uuid.UUID, *, lock: bool = False
) -> Prestamo:
    prestamo = await session.get(Prestamo, prestamo_id, with_for_update=lock)
    if prestamo is None:
        raise _not_found("El préstamo")
    if not ve_todo(principal):
        propio = await escribano_de(session, principal.user)
        if propio is None or propio.id not in (
            prestamo.escribano_id,
            prestamo.garante_escribano_id,
        ):
            raise _not_found("El préstamo")
    return prestamo


async def list_prestamos(
    session: AsyncSession,
    principal: Principal,
    estado: EstadoPrestamo | None,
    escribano_id: uuid.UUID | None,
) -> list[Prestamo]:
    stmt = select(Prestamo)
    if not ve_todo(principal):
        propio = await escribano_de(session, principal.user)
        if propio is None:
            return []
        stmt = stmt.where(
            or_(Prestamo.escribano_id == propio.id, Prestamo.garante_escribano_id == propio.id)
        )
    elif escribano_id is not None:
        stmt = stmt.where(Prestamo.escribano_id == escribano_id)
    if estado is not None:
        stmt = stmt.where(Prestamo.estado == estado.value)
    return list((await session.scalars(stmt.order_by(Prestamo.numero.desc()))).all())


async def plan_guardado(session: AsyncSession, prestamo_id: uuid.UUID) -> list[CuotaPrestamo]:
    result = await session.scalars(
        select(CuotaPrestamo)
        .where(CuotaPrestamo.prestamo_id == prestamo_id)
        .order_by(CuotaPrestamo.numero)
    )
    return list(result.all())


async def reevaluar(session: AsyncSession, prestamo: Prestamo, hoy: date) -> Evaluacion:
    """La solicitud con los datos de hoy, manteniendo las condiciones pactadas."""
    linea = await get_linea(session, prestamo.linea_id)
    return await evaluar(
        session,
        linea,
        capital=prestamo.capital,
        cuotas=prestamo.cuotas,
        hoy=hoy,
        escribano=await get_escribano(session, prestamo.escribano_id),
        ingreso_neto=prestamo.ingreso_neto,
        garante_id=prestamo.garante_escribano_id,
        excluir=prestamo.id,
        condiciones=(Sistema(prestamo.sistema), prestamo.tna, prestamo.tasa_es_ejemplo),
    )


async def _cuatro_ojos(session: AsyncSession, prestamo: Prestamo, actor: User) -> None:
    """Resuelve otra persona, que además no es el titular ni el garante del préstamo."""
    if prestamo.creado_por_user_id == actor.id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Quien cargó la solicitud no puede resolverla: la resuelve otra persona.",
            type_="urn:suite-notarial:prestamos:cuatro-ojos",
        )
    propio = await escribano_de(session, actor)
    if propio is not None and propio.id in (prestamo.escribano_id, prestamo.garante_escribano_id):
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "No podés resolver un préstamo en el que sos titular o garante.",
            type_="urn:suite-notarial:prestamos:cuatro-ojos",
        )


async def _bloquear_escribano(session: AsyncSession, escribano_id: uuid.UUID) -> None:
    """Serializa los otorgamientos de un mismo escribano hasta el fin de la transacción.

    Sin esto, dos préstamos otorgados a la vez podrían pasar cada uno el tope de afectación
    sin ver al otro.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(f"prestamos:{escribano_id}")))
    )


async def otorgar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, prestamo_id: uuid.UUID
) -> Prestamo:
    prestamo = await get_prestamo(session, principal, prestamo_id, lock=True)
    if prestamo.estado != EstadoPrestamo.SOLICITADO.value:
        raise _conflict("La solicitud ya fue resuelta.")
    await _cuatro_ojos(session, prestamo, principal.user)
    await _bloquear_escribano(session, prestamo.escribano_id)
    hoy = today_local()
    ev = await reevaluar(session, prestamo, hoy)
    _rechazar_si_hay(ev.impedimentos, status=HTTPStatus.CONFLICT)
    assert ev.afectacion is not None  # noqa: S101 - la solicitud tiene ingreso neto
    for c in ev.plan:
        session.add(
            CuotaPrestamo(
                prestamo_id=prestamo.id,
                numero=c.numero,
                vencimiento=c.vencimiento,
                saldo_inicial=c.saldo_inicial,
                amortizacion=c.amortizacion,
                interes=c.interes,
                cuota=c.cuota,
                saldo_final=c.saldo_final,
                estado=PENDIENTE,
            )
        )
    await session.flush()
    prestamo.otras_cuotas = ev.otras_cuotas
    prestamo.cuota_maxima = ev.cuota_maxima
    prestamo.afectacion = ev.afectacion
    prestamo.estado = VIGENTE
    prestamo.fecha_otorgamiento = hoy
    prestamo.resuelto_por_user_id = principal.user.id
    prestamo.resuelto_en = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PRESTAMO_OTORGADO,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        old_value={"estado": EstadoPrestamo.SOLICITADO.value},
        new_value={
            "estado": VIGENTE,
            "capital": f"{prestamo.capital:.2f}",
            "cuotas": prestamo.cuotas,
            "tna": f"{prestamo.tna:.4f}",
            "primer_vencimiento": ev.plan[0].vencimiento.isoformat(),
            "total_intereses": f"{sum((c.interes for c in ev.plan), CERO):.2f}",
        },
        details={"prestamo_id": str(prestamo.id), "numero": prestamo.numero},
    )
    await session.commit()
    await session.refresh(prestamo)
    return prestamo


async def rechazar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    prestamo_id: uuid.UUID,
    motivo: str,
) -> Prestamo:
    prestamo = await get_prestamo(session, principal, prestamo_id, lock=True)
    if prestamo.estado != EstadoPrestamo.SOLICITADO.value:
        raise _conflict("La solicitud ya fue resuelta.")
    await _cuatro_ojos(session, prestamo, principal.user)
    prestamo.estado = EstadoPrestamo.RECHAZADO.value
    prestamo.motivo_rechazo = motivo
    prestamo.resuelto_por_user_id = principal.user.id
    prestamo.resuelto_en = datetime.now(UTC)
    record_audit(
        session,
        ctx,
        AuditEvent.PRESTAMO_RECHAZADO,
        actor_user_id=principal.user.id,
        old_value={"estado": EstadoPrestamo.SOLICITADO.value},
        new_value={"estado": EstadoPrestamo.RECHAZADO.value},
        details={"prestamo_id": str(prestamo.id), "numero": prestamo.numero, "motivo": motivo},
    )
    await session.commit()
    await session.refresh(prestamo)
    return prestamo


async def registrar_pago(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    prestamo_id: uuid.UUID,
    numero: int,
    fecha_pago: date,
    importe: Decimal,
) -> Prestamo:
    """Cobro de una cuota (en orden). Con la última, el préstamo queda cancelado."""
    prestamo = await get_prestamo(session, principal, prestamo_id, lock=True)
    if prestamo.estado != VIGENTE:
        raise _conflict("El préstamo no está vigente.")
    cuotas = await plan_guardado(session, prestamo.id)
    pendientes = [c for c in cuotas if c.estado == PENDIENTE]
    if not pendientes or pendientes[0].numero != numero:
        raise _conflict(
            f"Las cuotas se cobran en orden: la próxima es la N° {pendientes[0].numero}."
            if pendientes
            else "El préstamo no tiene cuotas pendientes."
        )
    cuota = pendientes[0]
    assert prestamo.fecha_otorgamiento is not None  # noqa: S101 - vigente
    if fecha_pago > today_local() or fecha_pago < prestamo.fecha_otorgamiento:
        raise _invalid("La fecha de pago tiene que estar entre el otorgamiento y hoy.")
    # TODO(negocio): interés punitorio si se paga después del vencimiento; por ahora se cobra
    # exactamente la cuota del plan y el atraso queda registrado en la auditoría.
    if importe != cuota.cuota:
        raise _invalid(f"El importe tiene que ser el de la cuota: {format_pesos(cuota.cuota)}.")
    cuota.estado = EstadoCuota.PAGADA.value
    cuota.fecha_pago = fecha_pago
    cuota.importe_pagado = importe
    cuota.registrado_por_user_id = principal.user.id
    atraso = max(0, (fecha_pago - cuota.vencimiento).days)
    record_audit(
        session,
        ctx,
        AuditEvent.PRESTAMO_CUOTA_PAGADA,
        severity=Severity.WARNING if atraso else Severity.INFO,
        actor_user_id=principal.user.id,
        new_value={"cuota": numero, "importe": f"{importe:.2f}", "fecha_pago": str(fecha_pago)},
        details={"prestamo_id": str(prestamo.id), "dias_atraso": atraso},
    )
    if len(pendientes) == 1:
        await session.flush()
        prestamo.estado = EstadoPrestamo.CANCELADO.value
        record_audit(
            session,
            ctx,
            AuditEvent.PRESTAMO_CANCELADO,
            actor_user_id=principal.user.id,
            old_value={"estado": VIGENTE},
            new_value={"estado": EstadoPrestamo.CANCELADO.value},
            details={"prestamo_id": str(prestamo.id), "numero": prestamo.numero},
        )
    await session.commit()
    await session.refresh(prestamo)
    return prestamo
