"""Reportes: paginación en servidor y paridad exacta pantalla == XLSX == CSV (regla REP)."""

import csv
import io
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.reportes.catalogo import REPORTES
from app.modules.reportes.framework import Tipo
from tests.ddjj.conftest import Escenario, _escribano

ENCABEZADO_XLSX = 5


def test_cada_consulta_devuelve_las_columnas_declaradas() -> None:
    for reporte in REPORTES.values():
        stmt = reporte.construir({})
        assert list(stmt.selected_columns.keys()) == reporte.keys, reporte.codigo


async def _pantalla(client: AsyncClient, codigo: str, **filtros: str) -> dict[str, Any]:
    """Recorre todas las páginas (de a 2 filas) como lo haría la grilla."""
    filas: list[dict[str, Any]] = []
    page = 1
    while True:
        r = await client.get(
            f"/api/v1/reportes/{codigo}", params={**filtros, "page": page, "page_size": 2}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        filas += body["items"]
        if page * 2 >= body["total"]:
            return {"filas": filas, "total": body["total"], "totales": body["totales"]}
        page += 1


def _dec(valor: Any) -> Decimal:
    return (
        Decimal(str(valor).replace(".", "").replace(",", "."))
        if "," in str(valor)
        else Decimal(str(valor))
    )


@pytest.mark.parametrize(
    ("codigo", "filtros"),
    [
        ("BOLETAS", {}),
        ("BOLETAS", {"periodo_desde": "2026-08", "estado": "PENDIENTE"}),
        ("PAGOS", {}),
        ("RECAUDACION", {}),
        # Cada exportación agrega su propio evento: se filtra uno que no cambia entre corridas.
        ("AUDITORIA", {"evento": "boleta_emitida"}),
    ],
)
async def test_paridad_pantalla_xlsx_csv(
    auditor: AsyncClient, datos: dict[str, Any], codigo: str, filtros: dict[str, str]
) -> None:
    reporte = REPORTES[codigo]
    pantalla = await _pantalla(auditor, codigo, **filtros)
    xlsx = await auditor.get(
        f"/api/v1/reportes/{codigo}/export", params={**filtros, "formato": "xlsx"}
    )
    csv_r = await auditor.get(
        f"/api/v1/reportes/{codigo}/export", params={**filtros, "formato": "csv"}
    )
    assert xlsx.status_code == 200 and csv_r.status_code == 200
    assert pantalla["total"] > 0

    hoja = load_workbook(io.BytesIO(xlsx.content)).active
    assert hoja is not None
    encabezados = [c.value for c in hoja[ENCABEZADO_XLSX]]
    assert encabezados == [c.label for c in reporte.columnas]
    datos_xlsx = list(
        hoja.iter_rows(
            min_row=ENCABEZADO_XLSX + 1,
            max_row=ENCABEZADO_XLSX + pantalla["total"],
            values_only=True,
        )
    )
    totales_xlsx = next(
        hoja.iter_rows(
            min_row=ENCABEZADO_XLSX + pantalla["total"] + 1,
            max_row=ENCABEZADO_XLSX + pantalla["total"] + 1,
            values_only=True,
        )
    )
    filas_csv = list(csv.reader(io.StringIO(csv_r.content.decode("utf-8-sig")), delimiter=";"))
    assert filas_csv[0] == [c.label for c in reporte.columnas]
    datos_csv, totales_csv = filas_csv[1:-1], filas_csv[-1]

    assert len(datos_xlsx) == len(datos_csv) == len(pantalla["filas"]) == pantalla["total"]
    for i, col in enumerate(reporte.columnas):
        if not col.total:
            continue
        en_pantalla = Decimal(str(pantalla["totales"][col.key]))
        suma_filas = sum((Decimal(str(f[col.key] or 0)) for f in pantalla["filas"]), Decimal(0))
        suma_xlsx = sum((Decimal(str(f[i] or 0)) for f in datos_xlsx), Decimal(0))
        suma_csv = sum((_dec(f[i] or "0") for f in datos_csv), Decimal(0))
        assert suma_filas == suma_xlsx == suma_csv == en_pantalla, col.key
        assert Decimal(str(totales_xlsx[i])) == en_pantalla
        assert _dec(totales_csv[i]) == en_pantalla
    # Mismo orden fila a fila en las tres salidas (primera columna).
    primera = reporte.columnas[0]
    if primera.tipo is Tipo.ENTERO:
        assert [f[primera.key] for f in pantalla["filas"]] == [r[0] for r in datos_xlsx]


async def test_boletas_sin_anuladas_salvo_que_se_pidan(
    auditor: AsyncClient, datos: dict[str, Any]
) -> None:
    todas = await _pantalla(auditor, "BOLETAS")
    anuladas = await _pantalla(auditor, "BOLETAS", estado="ANULADA")
    pagadas = await _pantalla(auditor, "BOLETAS", estado="PAGADA", periodo_desde="2026-08")

    numeros = {f["numero"] for f in todas["filas"]}
    assert datos["anulada"]["numero"] not in numeros
    assert {datos["pagada"]["numero"], datos["pendiente"]["numero"]} <= numeros
    assert [f["numero"] for f in anuladas["filas"]] == [datos["anulada"]["numero"]]
    assert pagadas["totales"]["total_a_pagar"] == datos["pagada"]["total_a_pagar"]


async def test_recaudacion_cuenta_solo_lo_confirmado(
    auditor: AsyncClient, datos: dict[str, Any]
) -> None:
    rec = await _pantalla(auditor, "RECAUDACION")

    assert [f["periodo"] for f in rec["filas"]] == ["2026-08"]
    assert rec["totales"]["total_cobrado"] == datos["pagada"]["total_a_pagar"]
    assert rec["totales"]["boletas"] == 1


async def test_exportacion_auditada(
    auditor: AsyncClient, datos: dict[str, Any], db_session: AsyncSession
) -> None:
    await auditor.get(
        "/api/v1/reportes/PAGOS/export",
        params={"formato": "csv", "resultado": "APROBADO", "fecha_desde": "2026-10-01"},
    )

    log = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "REPORTE_EXPORTADO")
    )
    assert log is not None and log.details is not None
    assert log.details["reporte"] == "PAGOS"
    assert log.details["filtros"] == {"fecha_desde": "2026-10-01", "resultado": "APROBADO"}
    assert log.details["filas"] == 1
    assert log.details["totales"] == {"importe_confirmado": datos["pagada"]["total_a_pagar"]}
    assert "ROLE_AUDITOR" in log.details["roles"]


async def test_inyeccion_de_formulas(
    auditor: AsyncClient,
    staff: AsyncClient,
    datos: dict[str, Any],
    db_session: AsyncSession,
    escenario: Escenario,
) -> None:
    await _escribano(db_session, '=HYPERLINK("http://malicioso","clic")')
    await db_session.commit()

    xlsx = await staff.get("/api/v1/reportes/ESCRIBANOS/export", params={"formato": "xlsx"})
    csv_r = await staff.get("/api/v1/reportes/ESCRIBANOS/export", params={"formato": "csv"})
    pagos = await auditor.get("/api/v1/reportes/PAGOS/export", params={"formato": "csv"})

    hoja = load_workbook(io.BytesIO(xlsx.content)).active
    assert hoja is not None
    celdas = [c for fila in hoja.iter_rows() for c in fila if str(c.value).startswith("=HYPER")]
    assert celdas and all(c.data_type == "s" for c in celdas)
    texto = csv_r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in texto and "\n=HYPERLINK" not in texto
    assert '\'=HYPERLINK(""http://x"")' in pagos.content.decode("utf-8-sig")


async def test_permisos(
    notario: AsyncClient,
    staff: AsyncClient,
    auditor: AsyncClient,
    datos: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    disponibles_caja = [r["codigo"] for r in (await staff.get("/api/v1/reportes")).json()]
    disponibles_auditor = [r["codigo"] for r in (await auditor.get("/api/v1/reportes")).json()]

    assert disponibles_caja == ["ESCRIBANOS"]
    assert set(disponibles_auditor) == {
        "ESCRIBANOS",
        "BOLETAS",
        "PAGOS",
        "RECAUDACION",
        "AUDITORIA",
        "SUGERENCIAS_IA",
    }
    assert (await notario.get("/api/v1/reportes")).status_code == 403
    assert (await notario.get("/api/v1/reportes/BOLETAS/export")).status_code == 403
    assert (await staff.get("/api/v1/reportes/BOLETAS")).status_code == 403
    assert (await staff.get("/api/v1/reportes/AUDITORIA/export")).status_code == 403
    assert (await auditor.get("/api/v1/reportes/NO_EXISTE")).status_code == 404
    negados = (
        await db_session.scalars(
            select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PERMISSION_DENIED")
        )
    ).all()
    assert len(negados) >= 4


@pytest.mark.parametrize(
    "params",
    [
        {"periodo_desde": "2026-13"},
        {"periodo_desde": "2026-10", "periodo_hasta": "2026-01"},
        {"estado": "BORRADA"},
        {"registro": "uno"},
    ],
)
async def test_filtros_invalidos(
    auditor: AsyncClient, datos: dict[str, Any], params: dict[str, str]
) -> None:
    assert (await auditor.get("/api/v1/reportes/BOLETAS", params=params)).status_code == 422


async def test_exportar_exige_cabecera_csrf_y_no_se_cachea(
    auditor: AsyncClient, datos: dict[str, Any], db_session: AsyncSession
) -> None:
    sin_cabecera = await auditor.get(
        "/api/v1/reportes/BOLETAS/export",
        params={"formato": "csv"},
        headers={"X-Requested-With": ""},
    )
    grilla = await auditor.get("/api/v1/reportes/BOLETAS")

    assert sin_cabecera.status_code == 403
    assert sin_cabecera.json()["type"] == "urn:suite-notarial:csrf"
    assert grilla.headers["cache-control"] == "no-store"
    exportaciones = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "REPORTE_EXPORTADO")
    )
    assert exportaciones is None
