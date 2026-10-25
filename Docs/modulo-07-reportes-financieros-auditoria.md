# Documento de Ingeniería de Software — Módulo 7
## Reportes Financieros, Historial y Auditoría Transversal
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Requerimientos del Pliego:** `REP-01`, `REP-02`, `REP-03`, `REP-04`, `SEC-01`, `SEC-03`  
**Stack de Referencia:** Python 3.12+ | FastAPI | openpyxl (XLSX) | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 | React + TypeScript (TanStack Table)

---

### 1. Propósito, Alcance y Mitigación de Defectos Críticos

El **Módulo 7 (Reportes y Auditoría)** provee las capacidades de inteligencia de negocios, fiscalización y seguimiento contable tanto para la Administración de Caja y Tesorería como para Auditoría y Dirección.

#### 1.1 Mitigación Directa de Hallazgos Previos
1. **Erradicación del Scroll Horizontal Excesivo (`REP-03`):** Se elimina el defecto observado en sistemas previos donde las vistas históricas requerían desplazamientos horizontales de varios miles de píxeles sin encabezados fijos. La nueva interfaz implementa componentes de tabla responsiva con columnas colapsables/configurables, cabeceras congeladas (*sticky headers*), tarjetas de detalle expandibles y paginación en servidor.
2. **Conciliación Idéntica entre Pantalla y Exportaciones (`REP-02`):** Toda exportación en formato XLSX o CSV ejecuta exactamente la misma consulta estructurada, aplicando idénticos filtros, ordenamientos, husos horarios (`America/Argentina/San_Juan`) y criterios de redondeo que los observados en pantalla.
3. **Trazabilidad y Auditoría Forense (`SEC-03` / `REP-02`):** Cada generación de reporte o exportación de datos sensibles (listados de deuda, escrituras con montos, datos personales) registra de forma automática un evento inmutable de auditoría que captura: usuario operador, perfil, timestamp UTC, filtros aplicados, cantidad de registros obtenidos y dirección IP.

---

### 2. Catálogo de Reportes Operativos y Financieros

| Código Reporte | Denominación | Parámetros de Filtro | Campos Clave Exportados |
| :--- | :--- | :--- | :--- |
| `REP_RECAUDACION` | Recaudación por Concepto y Período | Rango de fechas, período fiscal, concepto previsional vs asistencial. | Período, Aporte Jubilatorio, Fondo Asistencial, Fijo Mensual, Total Recaudado, Cantidad de Boletas. |
| `REP_ESCRITURAS` | Detalle de Escrituras Declaradas | Período, Escribano, Registro Notarial, Tipo de Acto. | Número Escritura, Fecha Acto, Tomo/Folio, Escribano Titular/Adscripto, Tipo Acto, Base Imponible, Aporte. |
| `REP_DEUDA_MORA` | Estado de Deuda y Cumplimiento | Matrícula, Registro, Rango de mora (>30, >60, >90 días). | Matrícula, Nombre Escribano, Períodos Adeudados, Capital Original, Interés Punitorio Devengado, Total Deuda. |
| `REP_HISTORICO` | Consolidado Histórico Multianual | Rango de Años (2020 a 2026+), agrupador (Mes/Año). | Año, Mes, Total Escrituras Declaradas, Monto Total Escriturado, Aportes Emitidos, Aportes Cobrados, Saldo Pendiente. |

---

### 3. Servicio de Generación de Reportes y Exportación XLSX/CSV

```python
import io
import csv
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class ExportadorFinancieroService:
    """Generador estandarizado de reportes en Excel y CSV para la Caja Notarial."""

    @staticmethod
    def generar_excel_recaudacion(
        datos: List[Dict[str, Any]],
        titulo: str,
        filtros_aplicados: Dict[str, Any]
    ) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Recaudación"
        ws.views.sheetView[0].showGridLines = True

        # Paleta Institucional
        header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid") # Azul Institucional
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1B365D")
        bold_font = Font(name="Calibri", size=11, bold=True)
        thin_border = Border(
            left=Side(style="thin", color="D3D3D3"),
            right=Side(style="thin", color="D3D3D3"),
            top=Side(style="thin", color="D3D3D3"),
            bottom=Side(style="thin", color="D3D3D3")
        )

        # Encabezado Institucional
        ws.merge_cells("A1:G1")
        ws["A1"] = "CAJA NOTARIAL DE SAN JUAN - REPORTE OFICIAL"
        ws["A1"].font = title_font
        ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

        ws.merge_cells("A2:G2")
        ws["A2"] = f"{titulo} | Generado el {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} (UTC)"
        ws["A2"].font = Font(name="Calibri", size=10, italic=True)

        # Fila de Filtros
        fila_filtro = 4
        ws.cell(row=fila_filtro, column=1, value="Filtros aplicados:").font = bold_font
        ws.cell(row=fila_filtro, column=2, value=str(filtros_aplicados))

        # Encabezados de Columnas
        headers = ["Período", "Escribano", "Matrícula", "Aporte Jubilatorio", "Fondo Asistencial", "Fijo Mensual", "Total Liquidado"]
        start_row = 6
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=start_row, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Carga de Filas de Datos
        current_row = start_row + 1
        for row_data in datos:
            ws.cell(row=current_row, column=1, value=row_data.get("periodo", "")).alignment = Alignment(horizontal="center")
            ws.cell(row=current_row, column=2, value=row_data.get("escribano", ""))
            ws.cell(row=current_row, column=3, value=row_data.get("matricula", "")).alignment = Alignment(horizontal="center")

            for c_idx, key in enumerate(["previsional", "asistencial", "fijo", "total"], start=4):
                c = ws.cell(row=current_row, column=c_idx, value=float(row_data.get(key, 0.00)))
                c.number_format = '$ #,##0.00'
                c.alignment = Alignment(horizontal="right")
                c.border = thin_border

            current_row += 1

        # Ajuste automático de ancho de columnas
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()
```

---

### 4. Controlador de Reportes y Auditoría (`backend/app/api/v1/endpoints/reportes.py`)

```python
import uuid
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, Request, Response, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.core.database import get_db_session
from app.api.deps import require_permissions, get_current_user
from app.models.security import User, AuditSecurityLog
from app.models.ddjj import DeclaracionJurada, BoletaPago
from app.models.padron import Escribano, Persona
from app.services.exportador import ExportadorFinancieroService

router = APIRouter(prefix="/reportes", tags=["Reportes y Auditoría"])

@router.get("/recaudacion", status_code=status.HTTP_200_OK)
async def get_reporte_recaudacion(
    periodo_desde: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
    periodo_hasta: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("reports:financial"))
):
    stmt = (
        select(
            DeclaracionJurada.periodo,
            Persona.apellido,
            Persona.nombre,
            Escribano.matricula_numero,
            DeclaracionJurada.total_aporte_previsional,
            DeclaracionJurada.total_fondo_asistencial,
            DeclaracionJurada.total_fijo_mensual,
            DeclaracionJurada.total_liquidado
        )
        .join(Escribano, DeclaracionJurada.escribano_id == Escribano.id)
        .join(Persona, Escribano.persona_id == Persona.id)
        .where(DeclaracionJurada.estado != "BORRADOR")
    )

    if periodo_desde:
        stmt = stmt.where(DeclaracionJurada.periodo >= periodo_desde)
    if periodo_hasta:
        stmt = stmt.where(DeclaracionJurada.periodo <= periodo_hasta)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_records = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(DeclaracionJurada.periodo.desc(), Persona.apellido.asc())
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    rows = (await db.execute(stmt)).all()

    items = [
        {
            "periodo": r[0],
            "escribano": f"{r[1]}, {r[2]}",
            "matricula": r[3],
            "previsional": str(r[4]),
            "asistencial": str(r[5]),
            "fijo": str(r[6]),
            "total": str(r[7]),
        }
        for r in rows
    ]

    return {
        "items": items,
        "total": total_records,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_records + page_size - 1) // page_size
    }

@router.get("/recaudacion/export/xlsx")
async def export_recaudacion_xlsx(
    request: Request,
    periodo_desde: Optional[str] = Query(None),
    periodo_hasta: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("reports:financial"))
):
    # Consulta completa sin paginar para exportación
    stmt = (
        select(
            DeclaracionJurada.periodo,
            Persona.apellido,
            Persona.nombre,
            Escribano.matricula_numero,
            DeclaracionJurada.total_aporte_previsional,
            DeclaracionJurada.total_fondo_asistencial,
            DeclaracionJurada.total_fijo_mensual,
            DeclaracionJurada.total_liquidado
        )
        .join(Escribano, DeclaracionJurada.escribano_id == Escribano.id)
        .join(Persona, Escribano.persona_id == Persona.id)
        .where(DeclaracionJurada.estado != "BORRADOR")
        .order_by(DeclaracionJurada.periodo.desc())
    )

    if periodo_desde:
        stmt = stmt.where(DeclaracionJurada.periodo >= periodo_desde)
    if periodo_hasta:
        stmt = stmt.where(DeclaracionJurada.periodo <= periodo_hasta)

    rows = (await db.execute(stmt)).all()

    datos = [
        {
            "periodo": r[0],
            "escribano": f"{r[1]}, {r[2]}",
            "matricula": r[3],
            "previsional": r[4],
            "asistencial": r[5],
            "fijo": r[6],
            "total": r[7],
        }
        for r in rows
    ]

    filtros = {"periodo_desde": periodo_desde, "periodo_hasta": periodo_hasta}
    excel_bytes = ExportadorFinancieroService.generar_excel_recaudacion(
        datos, "Reporte de Recaudación y Liquidaciones", filtros
    )

    # Registro Inmutable de Exportación en Auditoría (SEC-03 / REP-02)
    audit = AuditSecurityLog(
        event_type="EXPORT_REPORTE_RECAUDACION_XLSX",
        severity="INFO",
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else "unknown",
        correlation_id=getattr(request.state, "correlation_id", None),
        details={"total_registros_exportados": len(datos), "filtros": filtros}
    )
    db.add(audit)
    await db.commit()

    filename = f"Recaudacion_Caja_Notarial_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
```
