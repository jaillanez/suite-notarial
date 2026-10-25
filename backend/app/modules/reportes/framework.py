"""Motor de reportes (regla REP).

Cada reporte declara sus columnas, sus filtros y UNA función que arma la consulta. La grilla
(paginada en el servidor), los totales y las exportaciones XLSX/CSV salen de esa misma consulta
con los mismos filtros y el mismo orden: la paridad entre pantalla y archivo es por construcción.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm

# Consulta de un reporte (Select con columnas etiquetadas por `key`).
type Consulta = Select[*tuple[Any, ...]]

PERIODO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Tope de filas por exportación: más que eso se acota con filtros.
MAX_FILAS_EXPORT = 50_000


class Tipo(StrEnum):
    TEXTO = "TEXTO"
    ENTERO = "ENTERO"
    MONEDA = "MONEDA"
    FECHA = "FECHA"
    FECHA_HORA = "FECHA_HORA"
    PERIODO = "PERIODO"
    CUIT = "CUIT"


class TipoFiltro(StrEnum):
    PERIODO = "PERIODO"
    FECHA = "FECHA"
    OPCIONES = "OPCIONES"
    TEXTO = "TEXTO"
    ENTERO = "ENTERO"


@dataclass(frozen=True)
class Columna:
    key: str
    label: str
    tipo: Tipo = Tipo.TEXTO
    # Se suma en la fila de totales (solo importes y cantidades).
    total: bool = False
    # Visible por defecto en pantalla; todas salen en la exportación.
    visible: bool = True


@dataclass(frozen=True)
class Filtro:
    key: str
    label: str
    tipo: TipoFiltro
    opciones: tuple[tuple[str, str], ...] = ()
    ayuda: str | None = None


Filtros = dict[str, Any]


@dataclass(frozen=True)
class Reporte:
    codigo: str
    titulo: str
    descripcion: str
    permiso: Perm
    columnas: tuple[Columna, ...]
    construir: Callable[[Filtros], Consulta]
    filtros: tuple[Filtro, ...] = field(default_factory=tuple)
    # Datos personales o de seguridad: la exportación se audita como WARNING.
    sensible: bool = False

    @property
    def keys(self) -> list[str]:
        return [c.key for c in self.columnas]


def _invalido(mensaje: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, mensaje)


def parsear_filtros(reporte: Reporte, params: dict[str, str]) -> Filtros:
    """Valida los filtros recibidos según su tipo. Las claves desconocidas se ignoran."""
    out: Filtros = {}
    for f in reporte.filtros:
        crudo = (params.get(f.key) or "").strip()
        if not crudo:
            continue
        if f.tipo is TipoFiltro.PERIODO:
            if not PERIODO_RE.match(crudo):
                raise _invalido(f"{f.label}: el período tiene el formato AAAA-MM.")
            out[f.key] = crudo
        elif f.tipo is TipoFiltro.FECHA:
            try:
                out[f.key] = date.fromisoformat(crudo)
            except ValueError as exc:
                raise _invalido(f"{f.label}: fecha inválida.") from exc
        elif f.tipo is TipoFiltro.OPCIONES:
            if crudo not in {v for v, _ in f.opciones}:
                raise _invalido(f"{f.label}: opción inválida.")
            out[f.key] = crudo
        elif f.tipo is TipoFiltro.ENTERO:
            if not crudo.isdigit() or len(crudo) > 9:
                raise _invalido(f"{f.label}: tiene que ser un número entero.")
            out[f.key] = int(crudo)
        else:
            out[f.key] = crudo[:100]
    for desde, hasta in (("periodo_desde", "periodo_hasta"), ("fecha_desde", "fecha_hasta")):
        if desde in out and hasta in out and out[desde] > out[hasta]:
            raise _invalido("El rango está invertido: «desde» es posterior a «hasta».")
    return out


@dataclass(frozen=True)
class Resultado:
    filas: list[dict[str, Any]]
    total_filas: int
    totales: dict[str, Decimal | int]


async def totales(
    session: AsyncSession, reporte: Reporte, stmt: Consulta
) -> tuple[int, dict[str, Decimal | int]]:
    """Cantidad de filas y sumas de las columnas totalizables, sobre la misma consulta."""
    sub = stmt.order_by(None).subquery()
    sumables = [c for c in reporte.columnas if c.total]
    fila = (
        await session.execute(
            select(
                func.count(),
                *(func.coalesce(func.sum(sub.c[c.key]), 0) for c in sumables),
            ).select_from(sub)
        )
    ).one()
    sumas: dict[str, Decimal | int] = {}
    for col, valor in zip(sumables, fila[1:], strict=True):
        sumas[col.key] = (
            Decimal(valor).quantize(Decimal("0.01")) if col.tipo is Tipo.MONEDA else int(valor)
        )
    return int(fila[0]), sumas


async def ejecutar(
    session: AsyncSession,
    reporte: Reporte,
    filtros: Filtros,
    *,
    offset: int | None = None,
    limit: int | None = None,
) -> Resultado:
    stmt = reporte.construir(filtros)
    total_filas, sumas = await totales(session, reporte, stmt)
    paginada = stmt
    if offset is not None:
        paginada = paginada.offset(offset)
    if limit is not None:
        paginada = paginada.limit(limit)
    filas = [dict(r._mapping) for r in (await session.execute(paginada)).all()]
    return Resultado(filas=filas, total_filas=total_filas, totales=sumas)
