"""Exportación XLSX y CSV de un reporte, con las mismas filas, orden y totales que la grilla.

- Importes como `Decimal` (XLSX numérico exacto con formato `#,##0.00`; CSV con coma decimal):
  nunca pasan por punto flotante (regla FIN).
- Fechas y horas en hora de San Juan.
- Protección contra inyección de fórmulas: un texto que empieza con `= + - @` se guarda como
  texto en XLSX y se antepone `'` en CSV.
"""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.common.cuit import format_cuit
from app.common.dates import LOCAL_TZ
from app.modules.reportes.framework import Columna, Reporte, Resultado, Tipo

FORMULA_PREFIJOS = ("=", "+", "-", "@", "\t", "\r")
PETROLEO = "113347"


def _periodo(valor: str) -> str:
    return f"{valor[5:7]}/{valor[:4]}"


def _local(valor: datetime) -> datetime:
    return valor.astimezone(LOCAL_TZ).replace(tzinfo=None)


def _decimal_ar(valor: Decimal) -> str:
    return f"{valor:.2f}".replace(".", ",")


def texto(col: Columna, valor: Any) -> str:
    """Representación textual (CSV y descripción de filtros)."""
    if valor is None:
        return ""
    if col.tipo is Tipo.MONEDA:
        return _decimal_ar(Decimal(valor))
    if col.tipo is Tipo.FECHA and isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if col.tipo is Tipo.FECHA_HORA and isinstance(valor, datetime):
        return _local(valor).strftime("%d/%m/%Y %H:%M:%S")
    if col.tipo is Tipo.PERIODO:
        return _periodo(str(valor))
    if col.tipo is Tipo.CUIT:
        return format_cuit(str(valor))
    return str(valor)


def _seguro(valor: str) -> str:
    return f"'{valor}" if valor.startswith(FORMULA_PREFIJOS) else valor


def describir_filtros(reporte: Reporte, filtros: dict[str, Any]) -> str:
    if not filtros:
        return "Sin filtros"
    partes = []
    for f in reporte.filtros:
        if f.key not in filtros:
            continue
        valor = filtros[f.key]
        etiqueta = dict(f.opciones).get(str(valor), valor)
        if isinstance(etiqueta, date):
            etiqueta = etiqueta.strftime("%d/%m/%Y")
        elif f.key.startswith("periodo"):
            etiqueta = _periodo(str(etiqueta))
        partes.append(f"{f.label}: {etiqueta}")
    return " · ".join(partes)


def a_csv(reporte: Reporte, resultado: Resultado) -> bytes:
    buffer = io.StringIO()
    # Punto y coma y coma decimal: lo que espera una planilla configurada en español (Argentina).
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([c.label for c in reporte.columnas])
    for fila in resultado.filas:
        writer.writerow(
            [
                _seguro(texto(c, fila[c.key])) if c.tipo is Tipo.TEXTO else texto(c, fila[c.key])
                for c in reporte.columnas
            ]
        )
    writer.writerow(_fila_totales(reporte, resultado, texto_plano=True))
    # BOM para que Excel lo abra como UTF-8 (tildes y eñes).
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _fila_totales(reporte: Reporte, resultado: Resultado, *, texto_plano: bool) -> list[Any]:
    fila: list[Any] = []
    for i, c in enumerate(reporte.columnas):
        if c.key in resultado.totales:
            valor = resultado.totales[c.key]
            fila.append(texto(c, valor) if texto_plano else valor)
        elif i == 0:
            fila.append(f"Total ({resultado.total_filas} filas)")
        else:
            fila.append("")
    return fila


def a_xlsx(
    reporte: Reporte, resultado: Resultado, filtros: dict[str, Any], generado: datetime, por: str
) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None  # noqa: S101 - un Workbook nuevo siempre tiene hoja activa
    ws.title = reporte.titulo[:31]
    n = len(reporte.columnas)
    ultima = get_column_letter(n)

    ws["A1"] = f"Caja Notarial de San Juan · {reporte.titulo}"
    ws["A1"].font = Font(size=14, bold=True, color=PETROLEO)
    ws["A2"] = (
        f"Generado el {_local(generado).strftime('%d/%m/%Y %H:%M')} (hora de San Juan) por {por}"
    )
    ws["A3"] = f"Filtros: {describir_filtros(reporte, filtros)}"
    for ref in ("A2", "A3"):
        ws[ref].font = Font(size=10, color="4C5C66")
        ws[ref].data_type = "s"

    encabezado = 5
    fill = PatternFill("solid", start_color=PETROLEO, end_color=PETROLEO)
    for i, c in enumerate(reporte.columnas, start=1):
        cell = ws.cell(row=encabezado, column=i, value=c.label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="right" if c.tipo is Tipo.MONEDA else "left")

    fila_n = encabezado
    for fila in resultado.filas:
        fila_n += 1
        for i, c in enumerate(reporte.columnas, start=1):
            _escribir(ws.cell(row=fila_n, column=i), c, fila[c.key])

    fila_n += 1
    borde = Border(top=Side(style="medium", color=PETROLEO))
    for i, valor in enumerate(_fila_totales(reporte, resultado, texto_plano=False), start=1):
        celda = ws.cell(row=fila_n, column=i)
        col = reporte.columnas[i - 1]
        if valor != "":
            if isinstance(valor, str):
                celda.value = valor
            else:
                _escribir(celda, col, valor)
        celda.font = Font(bold=True)
        celda.border = borde

    ws.freeze_panes = f"A{encabezado + 1}"
    if resultado.filas:
        ws.auto_filter.ref = f"A{encabezado}:{ultima}{encabezado + len(resultado.filas)}"
    for i, c in enumerate(reporte.columnas, start=1):
        ancho = 16 if c.tipo is Tipo.MONEDA else max(10, min(48, len(c.label) + 4))
        if c.tipo is Tipo.TEXTO:
            ancho = 28
        ws.column_dimensions[get_column_letter(i)].width = ancho

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _escribir(cell: Any, col: Columna, valor: Any) -> None:
    if valor is None:
        return
    if col.tipo is Tipo.MONEDA:
        # openpyxl escribe el Decimal tal cual en el XML (sin conversión binaria).
        cell.value = Decimal(valor).quantize(Decimal("0.01"))
        cell.number_format = "#,##0.00"
        cell.alignment = Alignment(horizontal="right")
    elif col.tipo is Tipo.ENTERO:
        cell.value = int(valor)
    elif col.tipo is Tipo.FECHA and isinstance(valor, date):
        cell.value = valor
        cell.number_format = "DD/MM/YYYY"
    elif col.tipo is Tipo.FECHA_HORA and isinstance(valor, datetime):
        cell.value = _local(valor)
        cell.number_format = "DD/MM/YYYY HH:MM:SS"
    else:
        cell.value = texto(col, valor)
        cell.data_type = "s"  # nunca una fórmula, aunque empiece con "="
