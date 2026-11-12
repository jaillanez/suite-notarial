"""Boletas del sistema anterior migradas sin registro («a completar»).

El origen tiene aportes pagados sin el registro y sin forma de deducirlo. Se migran con el nombre
de quien pagó y la Caja les asigna el registro después: una sola vez por boleta (la base no
admite otro cambio del histórico, ver `migracion_guard`) y queda auditado.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from http import HTTPStatus

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, record_audit
from app.core.errors import ProblemError
from app.modules.iam.models import User
from app.modules.migracion.models import HistoricoBoleta, HistoricoPago
from app.modules.padron.catalog import EstadoRegistro
from app.modules.padron.models import RegistroNotarial


async def sin_registro(session: AsyncSession) -> Sequence[tuple[HistoricoBoleta, object]]:
    """Boletas con el registro a completar y lo pagado de cada una, por escribano y período."""
    pagado = (
        select(func.coalesce(func.sum(HistoricoPago.importe), 0))
        .where(HistoricoPago.boleta_id == HistoricoBoleta.id)
        .correlate(HistoricoBoleta)
        .scalar_subquery()
    )
    filas = await session.execute(
        select(HistoricoBoleta, pagado)
        .where(HistoricoBoleta.registro_id.is_(None))
        .order_by(
            HistoricoBoleta.escribano_origen, HistoricoBoleta.periodo, HistoricoBoleta.codigo_legado
        )
    )
    return [(b, p) for b, p in filas.all()]


async def asignar_registro(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    boleta_ids: list[uuid.UUID],
    numero_registro: int,
) -> int:
    registro = await session.scalar(
        select(RegistroNotarial).where(RegistroNotarial.numero_registro == numero_registro)
    )
    if registro is None:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, f"No existe el Registro {numero_registro}."
        )
    boletas = (
        await session.scalars(
            select(HistoricoBoleta).where(HistoricoBoleta.id.in_(boleta_ids)).with_for_update()
        )
    ).all()
    if len(boletas) != len(set(boleta_ids)):
        raise ProblemError(HTTPStatus.NOT_FOUND, "Alguna de las boletas no existe.")
    ya = [b.codigo_legado for b in boletas if b.registro_id is not None]
    if ya:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            f"{len(ya)} de las boletas ya tienen registro: el histórico no se cambia "
            "(se asigna una sola vez).",
        )
    ahora = datetime.now(UTC)
    for b in boletas:
        b.registro_id = registro.id
        b.registro_asignado_por_user_id = actor.id
        b.registro_asignado_en = ahora
    record_audit(
        session,
        ctx,
        AuditEvent.MIGRACION_REGISTRO_ASIGNADO,
        actor_user_id=actor.id,
        old_value={"registro": None},
        new_value={"registro": numero_registro},
        details={
            "boletas": sorted(b.codigo_legado for b in boletas),
            "escribanos_origen": sorted({b.escribano_origen or "" for b in boletas}),
            "registro_cerrado": registro.estado == EstadoRegistro.CERRADO,
        },
    )
    await session.commit()
    return len(boletas)
