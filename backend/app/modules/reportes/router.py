"""Reportes con paginación en servidor y exportación XLSX/CSV: /api/v1/reportes (regla REP)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import LOCAL_TZ
from app.common.deps import SessionDep
from app.common.pagination import PageParamsDep
from app.core.errors import ProblemError
from app.modules.iam.deps import Principal, RequestContextDep, require_any_permission
from app.modules.reportes import exportar
from app.modules.reportes.catalogo import REPORTES
from app.modules.reportes.framework import (
    MAX_FILAS_EXPORT,
    Reporte,
    Tipo,
    TipoFiltro,
    ejecutar,
    parsear_filtros,
)

router = APIRouter(prefix="/reportes", tags=["reportes"])

PERMISOS_REPORTES = tuple(sorted({r.permiso for r in REPORTES.values()}, key=str))
# Exige sesión (y 2FA si el rol lo pide) con al menos un permiso de reportes; después se
# verifica el permiso propio de cada reporte.
CanReport = Annotated[Principal, Depends(require_any_permission(*PERMISOS_REPORTES))]


class ColumnaOut(BaseModel):
    key: str
    label: str
    tipo: Tipo
    total: bool
    visible: bool


class OpcionOut(BaseModel):
    value: str
    label: str


class FiltroOut(BaseModel):
    key: str
    label: str
    tipo: TipoFiltro
    opciones: list[OpcionOut]
    ayuda: str | None


class ReporteOut(BaseModel):
    codigo: str
    titulo: str
    descripcion: str
    sensible: bool
    columnas: list[ColumnaOut]
    filtros: list[FiltroOut]


Valor = str | int | None


class PaginaReporte(BaseModel):
    items: list[dict[str, Valor]]
    total: int
    page: int
    page_size: int
    # Sumas sobre TODAS las filas filtradas (no solo la página), igual que en la exportación.
    totales: dict[str, Valor]


class Formato(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"


def reporte_out(r: Reporte) -> ReporteOut:
    return ReporteOut(
        codigo=r.codigo,
        titulo=r.titulo,
        descripcion=r.descripcion,
        sensible=r.sensible,
        columnas=[
            ColumnaOut(key=c.key, label=c.label, tipo=c.tipo, total=c.total, visible=c.visible)
            for c in r.columnas
        ],
        filtros=[
            FiltroOut(
                key=f.key,
                label=f.label,
                tipo=f.tipo,
                opciones=[OpcionOut(value=v, label=lbl) for v, lbl in f.opciones],
                ayuda=f.ayuda,
            )
            for f in r.filtros
        ],
    )


def _json(valor: Any) -> Valor:
    """Importes como texto decimal (nunca float); fechas y horas en ISO."""
    if valor is None or isinstance(valor, int | str):
        return valor
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    return str(valor)


async def _reporte(
    codigo: str, principal: Principal, session: SessionDep, ctx: RequestContext
) -> Reporte:
    reporte = REPORTES.get(codigo.upper())
    if reporte is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El reporte no existe.")
    if reporte.permiso.value not in principal.permissions:
        record_audit(
            session,
            ctx,
            AuditEvent.PERMISSION_DENIED,
            severity=Severity.WARNING,
            actor_user_id=principal.user.id,
            details={"missing": [reporte.permiso.value], "path": ctx.path},
        )
        await session.commit()
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "No tenés permiso para ver este reporte.",
            type_="urn:suite-notarial:auth:forbidden",
            extra={"missing_permissions": [reporte.permiso.value]},
        )
    return reporte


@router.get("", response_model=list[ReporteOut])
async def listar(principal: CanReport) -> list[ReporteOut]:
    """Reportes disponibles para quien consulta, con sus columnas y filtros."""
    return [reporte_out(r) for r in REPORTES.values() if r.permiso.value in principal.permissions]


@router.get("/{codigo}", response_model=PaginaReporte)
async def ver(
    codigo: str,
    request: Request,
    principal: CanReport,
    session: SessionDep,
    ctx: RequestContextDep,
    page: PageParamsDep,
) -> PaginaReporte:
    reporte = await _reporte(codigo, principal, session, ctx)
    filtros = parsear_filtros(reporte, dict(request.query_params))
    resultado = await ejecutar(session, reporte, filtros, offset=page.offset, limit=page.page_size)
    return PaginaReporte(
        items=[{k: _json(v) for k, v in fila.items()} for fila in resultado.filas],
        total=resultado.total_filas,
        page=page.page,
        page_size=page.page_size,
        totales={k: _json(v) for k, v in resultado.totales.items()},
    )


@router.get(
    "/{codigo}/export",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "text/csv": {},
            }
        }
    },
)
async def exportar_reporte(
    codigo: str,
    request: Request,
    principal: CanReport,
    session: SessionDep,
    ctx: RequestContextDep,
    formato: Annotated[Formato, Query()] = Formato.XLSX,
) -> Response:
    """Misma consulta, filtros y orden que la grilla, sin paginar. Queda auditado."""
    reporte = await _reporte(codigo, principal, session, ctx)
    params = {k: v for k, v in request.query_params.items() if k != "formato"}
    filtros = parsear_filtros(reporte, params)
    resultado = await ejecutar(session, reporte, filtros, limit=MAX_FILAS_EXPORT + 1)
    if resultado.total_filas > MAX_FILAS_EXPORT:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"El reporte tiene {resultado.total_filas} filas: acotalo con filtros para exportar "
            f"(máximo {MAX_FILAS_EXPORT}).",
        )
    generado = datetime.now(UTC)
    if formato is Formato.XLSX:
        contenido = exportar.a_xlsx(reporte, resultado, filtros, generado, principal.user.email)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenido = exportar.a_csv(reporte, resultado)
        media = "text/csv; charset=utf-8"
    record_audit(
        session,
        ctx,
        AuditEvent.REPORTE_EXPORTADO,
        severity=Severity.WARNING if reporte.sensible else Severity.INFO,
        actor_user_id=principal.user.id,
        details={
            "reporte": reporte.codigo,
            "formato": formato.value,
            "filtros": {k: _json(v) for k, v in filtros.items()},
            "filas": resultado.total_filas,
            "totales": {k: _json(v) for k, v in resultado.totales.items()},
            "roles": sorted(principal.user.role_codes),
        },
    )
    await session.commit()
    nombre = f"{reporte.codigo.lower()}-{generado.astimezone(LOCAL_TZ).strftime('%Y%m%d-%H%M')}"
    return Response(
        content=contenido,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}.{formato.value}"',
            "Cache-Control": "no-store",
        },
    )
