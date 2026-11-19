"""DDJJ del sistema anterior: consulta de solo lectura del histórico migrado.

En el sistema anterior la DDJJ era del registro y del mes. Acá se arma con los actos migrados
(`historico_actos`) y las boletas con sus pagos (`historico_boletas`, `historico_pagos`) de cada
registro y período. Se ve con el mismo alcance que las DDJJ de la Suite: el personal de la Caja,
todas; un escribano, las de los registros y meses en que tuvo cargo.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from http import HTTPStatus

from sqlalchemy import Select, func, literal, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.ddjj.service import _alcance_ddjj
from app.modules.iam.deps import Principal
from app.modules.migracion.models import HistoricoActo, HistoricoBoleta, HistoricoPago
from app.modules.padron.models import Escribano, Persona, RegistroNotarial

CERO = Decimal("0.00")


@dataclass(frozen=True)
class DDJJAnterior:
    registro_id: uuid.UUID
    numero_registro: int
    periodo: str
    cantidad_actos: int
    total_aportes: Decimal
    total_boletas: Decimal
    total_pagado: Decimal


@dataclass(frozen=True)
class ActoAnterior:
    id: uuid.UUID
    tipo_protocolo: str | None
    numero_escritura: int
    folio: int | None
    fecha_acto: date | None
    naturaleza: str
    escribano: str | None
    cargo: str | None
    exento: bool
    base_imponible: Decimal | None
    aporte_variable: Decimal | None
    aporte_fijo: Decimal | None
    aporte: Decimal


@dataclass(frozen=True)
class BoletaAnterior:
    id: uuid.UUID
    numero: str | None
    fecha_emision: date
    fecha_vencimiento: date
    importe: Decimal
    estado: str
    pagado: Decimal
    fecha_pago: date | None


@dataclass(frozen=True)
class DDJJAnteriorDetalle:
    resumen: DDJJAnterior
    actos: list[ActoAnterior]
    boletas: list[BoletaAnterior]


async def _filtros(session: AsyncSession, principal: Principal) -> tuple[list, list] | None:  # type: ignore[type-arg]
    """Condiciones de alcance sobre actos y boletas. None: sin restricción. ([], []): nada."""
    alcance = await _alcance_ddjj(session, principal)
    if alcance is None:
        return None
    return (
        [a.condicion(HistoricoActo.registro_id, HistoricoActo.periodo) for a in alcance],
        [a.condicion(HistoricoBoleta.registro_id, HistoricoBoleta.periodo) for a in alcance],  # type: ignore[arg-type]
    )


def _claves(
    filtros: tuple[list, list] | None,  # type: ignore[type-arg]
    registro: int | None,
    periodo: str | None,
) -> Select:  # type: ignore[type-arg]
    actos = select(HistoricoActo.registro_id, HistoricoActo.periodo)
    boletas = select(
        HistoricoBoleta.registro_id.label("registro_id"), HistoricoBoleta.periodo
    ).where(HistoricoBoleta.registro_id.is_not(None))
    if filtros is not None:
        actos = actos.where(or_(*filtros[0]) if filtros[0] else literal(False))
        boletas = boletas.where(or_(*filtros[1]) if filtros[1] else literal(False))
    if periodo:
        actos = actos.where(HistoricoActo.periodo == periodo)
        boletas = boletas.where(HistoricoBoleta.periodo == periodo)
    claves = union(actos, boletas).subquery()
    stmt = select(claves.c.registro_id, claves.c.periodo, RegistroNotarial.numero_registro).join(
        RegistroNotarial, RegistroNotarial.id == claves.c.registro_id
    )
    if registro is not None:
        stmt = stmt.where(RegistroNotarial.numero_registro == registro)
    return stmt


def _resumenes(claves: Select) -> Select:  # type: ignore[type-arg]
    c = claves.subquery()
    actos = (
        select(
            HistoricoActo.registro_id,
            HistoricoActo.periodo,
            func.count().label("cantidad"),
            func.coalesce(func.sum(HistoricoActo.importe), 0).label("aportes"),
        )
        .group_by(HistoricoActo.registro_id, HistoricoActo.periodo)
        .subquery()
    )
    pagos = (
        select(HistoricoPago.boleta_id, func.sum(HistoricoPago.importe).label("pagado"))
        .group_by(HistoricoPago.boleta_id)
        .subquery()
    )
    boletas = (
        select(
            HistoricoBoleta.registro_id,
            HistoricoBoleta.periodo,
            func.coalesce(func.sum(HistoricoBoleta.importe), 0).label("importe"),
            func.coalesce(func.sum(pagos.c.pagado), 0).label("pagado"),
        )
        .outerjoin(pagos, pagos.c.boleta_id == HistoricoBoleta.id)
        .where(HistoricoBoleta.estado != "ANULADA")
        .group_by(HistoricoBoleta.registro_id, HistoricoBoleta.periodo)
        .subquery()
    )
    return (
        select(
            c.c.registro_id,
            c.c.numero_registro,
            c.c.periodo,
            func.coalesce(actos.c.cantidad, 0).label("cantidad"),
            func.coalesce(actos.c.aportes, 0).label("aportes"),
            func.coalesce(boletas.c.importe, 0).label("importe"),
            func.coalesce(boletas.c.pagado, 0).label("pagado"),
        )
        .outerjoin(
            actos,
            (actos.c.registro_id == c.c.registro_id) & (actos.c.periodo == c.c.periodo),
        )
        .outerjoin(
            boletas,
            (boletas.c.registro_id == c.c.registro_id) & (boletas.c.periodo == c.c.periodo),
        )
    )


def _resumen(fila: object) -> DDJJAnterior:
    return DDJJAnterior(
        registro_id=fila.registro_id,  # type: ignore[attr-defined]
        numero_registro=fila.numero_registro,  # type: ignore[attr-defined]
        periodo=fila.periodo,  # type: ignore[attr-defined]
        cantidad_actos=int(fila.cantidad),  # type: ignore[attr-defined]
        total_aportes=Decimal(fila.aportes).quantize(CERO),  # type: ignore[attr-defined]
        total_boletas=Decimal(fila.importe).quantize(CERO),  # type: ignore[attr-defined]
        total_pagado=Decimal(fila.pagado).quantize(CERO),  # type: ignore[attr-defined]
    )


async def listar(
    session: AsyncSession,
    principal: Principal,
    page: PageParams,
    *,
    registro: int | None = None,
    periodo: str | None = None,
) -> tuple[list[DDJJAnterior], int]:
    """DDJJ del sistema anterior, de la más reciente a la más vieja."""
    filtros = await _filtros(session, principal)
    claves = _claves(filtros, registro, periodo)
    total = await session.scalar(select(func.count()).select_from(claves.subquery()))
    stmt = _resumenes(claves)
    orden = stmt.selected_columns
    filas = (
        await session.execute(
            stmt.order_by(orden.periodo.desc(), orden.numero_registro)
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    return [_resumen(f) for f in filas], int(total or 0)


async def detalle(
    session: AsyncSession, principal: Principal, registro_id: uuid.UUID, periodo: str
) -> DDJJAnteriorDetalle:
    filtros = await _filtros(session, principal)
    claves = _claves(filtros, None, periodo).where(RegistroNotarial.id == registro_id)
    fila = (await session.execute(_resumenes(claves))).first()
    if fila is None:
        # No se revela si existe en un registro ajeno.
        raise ProblemError(HTTPStatus.NOT_FOUND, "La declaración jurada no existe.")
    persona = (
        select(Escribano.id, func.concat(Persona.apellido, ", ", Persona.nombre).label("nombre"))
        .join(Persona, Persona.id == Escribano.persona_id)
        .subquery()
    )
    actos = (
        await session.execute(
            select(HistoricoActo, persona.c.nombre)
            .outerjoin(persona, persona.c.id == HistoricoActo.escribano_id)
            .where(HistoricoActo.registro_id == registro_id, HistoricoActo.periodo == periodo)
            .order_by(
                HistoricoActo.tipo_protocolo,
                HistoricoActo.numero_escritura,
                HistoricoActo.codigo_legado,
            )
        )
    ).all()
    pagos = (
        select(
            HistoricoPago.boleta_id,
            func.sum(HistoricoPago.importe).label("pagado"),
            func.max(HistoricoPago.fecha_pago).label("fecha_pago"),
        )
        .group_by(HistoricoPago.boleta_id)
        .subquery()
    )
    boletas = (
        await session.execute(
            select(HistoricoBoleta, pagos.c.pagado, pagos.c.fecha_pago)
            .outerjoin(pagos, pagos.c.boleta_id == HistoricoBoleta.id)
            .where(HistoricoBoleta.registro_id == registro_id, HistoricoBoleta.periodo == periodo)
            .order_by(HistoricoBoleta.fecha_emision)
        )
    ).all()
    return DDJJAnteriorDetalle(
        resumen=_resumen(fila),
        actos=[
            ActoAnterior(
                id=a.id,
                tipo_protocolo=a.tipo_protocolo,
                numero_escritura=a.numero_escritura,
                folio=a.folio,
                fecha_acto=a.fecha_acto,
                naturaleza=a.naturaleza,
                escribano=nombre or a.escribano_origen,
                cargo=a.cargo,
                exento=a.exento,
                base_imponible=a.base_imponible,
                aporte_variable=a.aporte_variable,
                aporte_fijo=a.aporte_fijo,
                aporte=a.importe,
            )
            for a, nombre in actos
        ],
        boletas=[
            BoletaAnterior(
                id=b.id,
                numero=b.numero_boleta,
                fecha_emision=b.fecha_emision,
                fecha_vencimiento=b.fecha_vencimiento,
                importe=b.importe,
                estado=b.estado,
                pagado=Decimal(pagado or 0).quantize(CERO),
                fecha_pago=fecha_pago,
            )
            for b, pagado, fecha_pago in boletas
        ],
    )
