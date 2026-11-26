"""Créditos y débitos sobre boletas (Caja, 26/11/2026).

La administración de la Caja cuadra la cuenta de un escribano con ajustes justificados:
centavos de más o de menos al pagar, rebaja de intereses o condonación que resolvió la Junta,
o la diferencia de una rectificativa. Un crédito baja lo que se debe de la boleta; un débito
lo sube.

- Lo propone una persona y lo aprueba otra (cuatro ojos, también en la base).
- Solo cuentan los aprobados: el saldo de la boleta es el total menos los créditos más los
  débitos aprobados. Tesorería confirma un pago por ese saldo, y el botón de pago lo publica.
- Si los créditos cubren todo el total, la boleta queda pagada al aprobar el último.
- Nada se borra ni se edita: un error se corrige con otro ajuste en sentido contrario.

Es una herramienta de la Caja: ningún cálculo automático propone ajustes (regla HIC).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.money import format_pesos, to_money
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.ddjj.catalog import EstadoBoleta
from app.modules.ddjj.models import Boleta
from app.modules.iam.deps import Principal
from app.modules.pagos.catalog import (
    CONCEPTOS_CON_RESOLUCION,
    ConceptoAjuste,
    EstadoAjuste,
    EstadoComprobante,
    TipoAjuste,
)
from app.modules.pagos.models import Ajuste, Comprobante

CERO = Decimal("0.00")


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _invalid(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, message)


def _signo() -> ColumnElement[Decimal]:
    return case((Ajuste.tipo == TipoAjuste.CREDITO.value, -Ajuste.importe), else_=Ajuste.importe)


async def ajustado(
    session: AsyncSession, boleta_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Neto de los ajustes aprobados por boleta: negativo si bajan lo que se debe."""
    ids = list(boleta_ids)
    if not ids:
        return {}
    filas = await session.execute(
        select(Ajuste.boleta_id, func.sum(_signo()))
        .where(Ajuste.boleta_id.in_(ids), Ajuste.estado == EstadoAjuste.APROBADO.value)
        .group_by(Ajuste.boleta_id)
    )
    return {boleta_id: to_money(neto) for boleta_id, neto in filas.all()}


async def saldo(session: AsyncSession, boleta: Boleta) -> Decimal:
    """Lo que hay que pagar de la boleta: el total con los ajustes aprobados."""
    neto = (await ajustado(session, [boleta.id])).get(boleta.id, CERO)
    return to_money(boleta.total_a_pagar + neto)


async def saldos(session: AsyncSession, boletas: Iterable[Boleta]) -> dict[uuid.UUID, Decimal]:
    lista = list(boletas)
    netos = await ajustado(session, (b.id for b in lista))
    return {b.id: to_money(b.total_a_pagar + netos.get(b.id, CERO)) for b in lista}


async def de_la_boleta(session: AsyncSession, boleta_id: uuid.UUID) -> list[Ajuste]:
    result = await session.scalars(
        select(Ajuste).where(Ajuste.boleta_id == boleta_id).order_by(Ajuste.propuesto_en)
    )
    return list(result.all())


@dataclass(frozen=True)
class Propuesta:
    tipo: TipoAjuste
    concepto: ConceptoAjuste
    importe: Decimal
    justificacion: str
    resolucion: str | None


def _valores(a: Ajuste) -> dict[str, str | None]:
    return {
        "tipo": a.tipo,
        "concepto": a.concepto,
        "importe": f"{a.importe:.2f}",
        "justificacion": a.justificacion,
        "resolucion": a.resolucion,
        "estado": a.estado,
    }


async def _boleta_pendiente(session: AsyncSession, boleta_id: uuid.UUID) -> Boleta:
    boleta = await session.get(Boleta, boleta_id, with_for_update=True)
    if boleta is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La boleta no existe.")
    if boleta.estado != EstadoBoleta.PENDIENTE.value:
        estado = "pagada" if boleta.estado == EstadoBoleta.PAGADA.value else "anulada"
        raise _conflict(
            f"La boleta N° {boleta.numero} está {estado}: los ajustes se hacen sobre una boleta "
            "pendiente (para otra, usá su boleta siguiente)."
        )
    return boleta


def _controlar_saldo(boleta: Boleta, saldo_actual: Decimal, tipo: str, importe: Decimal) -> None:
    if tipo == TipoAjuste.CREDITO.value and importe > saldo_actual:
        raise _invalid(
            f"El crédito ({format_pesos(importe)}) supera lo que queda por pagar de la boleta "
            f"N° {boleta.numero} ({format_pesos(saldo_actual)})."
        )


async def proponer(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    boleta_id: uuid.UUID,
    data: Propuesta,
) -> Ajuste:
    boleta = await _boleta_pendiente(session, boleta_id)
    if data.concepto in CONCEPTOS_CON_RESOLUCION and not data.resolucion:
        raise _invalid("Indicá la resolución de la Junta que dispone este ajuste.")
    importe = to_money(data.importe)
    _controlar_saldo(boleta, await saldo(session, boleta), data.tipo.value, importe)
    ajuste = Ajuste(
        id=uuid.uuid4(),
        boleta_id=boleta.id,
        tipo=data.tipo.value,
        concepto=data.concepto.value,
        importe=importe,
        justificacion=data.justificacion,
        resolucion=data.resolucion,
        estado=EstadoAjuste.PROPUESTO.value,
        propuesto_por_user_id=principal.user.id,
    )
    session.add(ajuste)
    record_audit(
        session,
        ctx,
        AuditEvent.AJUSTE_PROPUESTO,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        new_value=_valores(ajuste),
        details={"ajuste_id": str(ajuste.id), "boleta": boleta.numero},
    )
    await session.commit()
    return ajuste


async def _para_resolver(
    session: AsyncSession, principal: Principal, ajuste_id: uuid.UUID
) -> tuple[Ajuste, Boleta]:
    ajuste = await session.get(Ajuste, ajuste_id, with_for_update=True)
    if ajuste is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El ajuste no existe.")
    if ajuste.estado != EstadoAjuste.PROPUESTO.value:
        raise _conflict("El ajuste ya fue resuelto.")
    if ajuste.propuesto_por_user_id == principal.user.id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Un ajuste lo aprueba o rechaza otra persona, no quien lo propuso.",
        )
    return ajuste, await _boleta_pendiente(session, ajuste.boleta_id)


async def aprobar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, ajuste_id: uuid.UUID
) -> Ajuste:
    ajuste, boleta = await _para_resolver(session, principal, ajuste_id)
    actual = await saldo(session, boleta)
    _controlar_saldo(boleta, actual, ajuste.tipo, ajuste.importe)
    nuevo = to_money(
        actual - ajuste.importe
        if ajuste.tipo == TipoAjuste.CREDITO.value
        else actual + ajuste.importe
    )
    en_revision = await session.scalar(
        select(func.count()).where(
            Comprobante.boleta_id == boleta.id,
            Comprobante.estado == EstadoComprobante.PENDIENTE_REVISION.value,
        )
    )
    if nuevo == CERO and en_revision:
        raise _conflict(
            "Con este ajuste la boleta queda sin saldo, pero tiene un pago en revisión: "
            "Tesorería tiene que resolverlo antes."
        )
    antes = _valores(ajuste)
    ajuste.estado = EstadoAjuste.APROBADO.value
    ajuste.resuelto_por_user_id = principal.user.id
    ajuste.resuelto_en = datetime.now(UTC)
    await session.flush()
    detalles = {
        "ajuste_id": str(ajuste.id),
        "boleta": boleta.numero,
        "saldo_anterior": f"{actual:.2f}",
        "saldo_nuevo": f"{nuevo:.2f}",
    }
    record_audit(
        session,
        ctx,
        AuditEvent.AJUSTE_APROBADO,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        target_user_id=ajuste.propuesto_por_user_id,
        old_value=antes,
        new_value=_valores(ajuste),
        details=detalles,
    )
    if nuevo == CERO:
        # Los créditos cubren todo lo que se debía: la boleta queda cancelada.
        boleta.estado = EstadoBoleta.PAGADA.value
        record_audit(
            session,
            ctx,
            AuditEvent.BOLETA_PAGADA,
            severity=Severity.WARNING,
            actor_user_id=principal.user.id,
            old_value={"estado": EstadoBoleta.PENDIENTE.value},
            new_value={"estado": EstadoBoleta.PAGADA.value},
            details={"boleta_id": str(boleta.id), "por_ajustes": True, **detalles},
        )
    await session.commit()
    return ajuste


async def rechazar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ajuste_id: uuid.UUID,
    motivo: str,
) -> Ajuste:
    ajuste = await session.get(Ajuste, ajuste_id, with_for_update=True)
    if ajuste is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El ajuste no existe.")
    if ajuste.estado != EstadoAjuste.PROPUESTO.value:
        raise _conflict("El ajuste ya fue resuelto.")
    if ajuste.propuesto_por_user_id == principal.user.id:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Un ajuste lo aprueba o rechaza otra persona, no quien lo propuso.",
        )
    antes = _valores(ajuste)
    ajuste.estado = EstadoAjuste.RECHAZADO.value
    ajuste.resuelto_por_user_id = principal.user.id
    ajuste.resuelto_en = datetime.now(UTC)
    ajuste.motivo_rechazo = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.AJUSTE_RECHAZADO,
        actor_user_id=principal.user.id,
        target_user_id=ajuste.propuesto_por_user_id,
        old_value=antes,
        new_value=_valores(ajuste),
        details={"ajuste_id": str(ajuste.id), "motivo": motivo},
    )
    await session.commit()
    return ajuste


async def listar(
    session: AsyncSession, page: PageParams, estado: EstadoAjuste | None
) -> tuple[list[Ajuste], int]:
    stmt = select(Ajuste)
    if estado is not None:
        stmt = stmt.where(Ajuste.estado == estado.value)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.scalars(
        stmt.order_by(Ajuste.propuesto_en.desc()).offset(page.offset).limit(page.page_size)
    )
    return list(result.all()), int(total or 0)
