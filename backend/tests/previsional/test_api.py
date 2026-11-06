"""API de aportes y puntos: informe (personal y propio), permisos 403, «Puntos sin vincular»,
vínculo manual auditado, cálculo deshabilitado y reporte por ejercicio (paridad de export)."""

import csv
import io
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog, RequestContext
from app.modules.iam.models import User
from app.modules.previsional import pdf, service
from app.modules.previsional.models import PuntosAfiliado
from app.modules.previsional.planilla import leer_planilla
from tests.ddjj.conftest import _client
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.previsional.conftest import Notario, crear_escribano

CTX = RequestContext(ip_address=None, user_agent="test", correlation_id=None)


@pytest.fixture
async def cargada(
    db_session: AsyncSession, operador: User, planilla_xlsx: Callable[..., Path]
) -> None:
    await service.cargar(
        db_session, leer_planilla(planilla_xlsx()), operador, "Planilla sintética", CTX
    )
    await db_session.commit()


async def _denegados(session: AsyncSession) -> int:
    return len(
        (
            await session.scalars(
                select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PERMISSION_DENIED")
            )
        ).all()
    )


async def test_informe_del_escribano_para_el_personal(
    caja: AsyncClient, notario_ana: Notario, cargada: None
) -> None:
    r = await caja.get(f"/api/v1/previsional/escribanos/{notario_ana.escribano.id}/puntos")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["escribano"]["apellido_nombre"] == "Prueba, Ana Sintética"
    assert body["filas"] == [
        {
            "anio": 1990,
            "fecha_inicio": "1989-09-01",
            "fecha_cierre": "1990-08-31",
            "aportes": "82466.67",
            "puntos": "97.639503",
        },
        {
            "anio": 1991,
            "fecha_inicio": "1990-09-01",
            "fecha_cierre": "1991-08-31",
            "aportes": "100.50",
            "puntos": "50.000000",
        },
    ]
    assert body["total_aportes"] == "82567.17"
    assert body["total_puntos"] == "147.639503"
    assert body["origenes"] == [
        {"nombre_origen": "PRUEBA Ana Sintética", "vinculacion": "EXACTA", "ejercicios": 2}
    ]


async def test_el_escribano_ve_solo_lo_suyo(
    notario_ana: Notario, cargada: None, db_session: AsyncSession
) -> None:
    otro = await crear_escribano(db_session, "Ajeno", "Escribano")
    await db_session.commit()
    ac = notario_ana.client

    propio = await ac.get("/api/v1/previsional/mis-puntos")
    por_id = await ac.get(f"/api/v1/previsional/escribanos/{notario_ana.escribano.id}/puntos")
    antes = await _denegados(db_session)
    ajeno = await ac.get(f"/api/v1/previsional/escribanos/{otro.id}/puntos")
    ajeno_pdf = await ac.get(f"/api/v1/previsional/escribanos/{otro.id}/puntos/pdf")
    sin_vincular = await ac.get("/api/v1/previsional/puntos/sin-vincular")

    assert propio.status_code == por_id.status_code == 200
    assert propio.json()["total_puntos"] == "147.639503"
    assert ajeno.status_code == ajeno_pdf.status_code == sin_vincular.status_code == 403
    assert ajeno.headers["content-type"] == "application/problem+json"
    assert await _denegados(db_session) >= antes + 3


async def test_sin_permiso_alguno(app: FastAPI, db_session: AsyncSession, cargada: None) -> None:
    publico = await make_user(db_session, roles=("ROLE_PUBLICO",))
    esc = await crear_escribano(db_session, "Prueba", "Ana Sintética")
    await db_session.commit()
    async with await _client(app) as ac:
        await login(ac, publico)
        for url in (
            "/api/v1/previsional/mis-puntos",
            f"/api/v1/previsional/escribanos/{esc.id}/puntos",
            "/api/v1/previsional/calculo",
        ):
            assert (await ac.get(url)).status_code == 403, url
        vincular = await ac.post(
            "/api/v1/previsional/puntos/vincular",
            json={"nombre_origen": "X", "escribano_id": str(esc.id)},
        )
        assert vincular.status_code == 403


async def test_escribano_sin_cuenta_vinculada(app: FastAPI, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    async with await _client(app) as ac:
        await login(ac, user)
        r = await ac.get("/api/v1/previsional/mis-puntos")
        assert r.status_code == 404
        assert (await ac.get("/api/v1/previsional/mis-puntos/pdf")).status_code == 404


async def test_informe_pdf(
    caja: AsyncClient, notario_ana: Notario, cargada: None, db_session: AsyncSession
) -> None:
    staff_pdf = await caja.get(
        f"/api/v1/previsional/escribanos/{notario_ana.escribano.id}/puntos/pdf"
    )
    propio_pdf = await notario_ana.client.get("/api/v1/previsional/mis-puntos/pdf")

    for r in (staff_pdf, propio_pdf):
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        assert r.headers["cache-control"] == "no-store"
    matricula = notario_ana.escribano.matricula_numero
    assert f"matricula-{matricula}.pdf" in staff_pdf.headers["content-disposition"]


async def test_html_del_informe(
    notario_ana: Notario, cargada: None, db_session: AsyncSession
) -> None:
    from datetime import date

    from app.core.config import get_settings

    await db_session.refresh(notario_ana.escribano, attribute_names=["persona"])
    informe = await service.informe(db_session, notario_ana.escribano)
    html = pdf.render_html(get_settings(), informe, date(2026, 11, 5))

    assert "CONFORME REGLAMENTACI" in html.upper()
    assert "Prueba, Ana Sintética" in html
    assert "$ 82.466,67" in html and "97,639503" in html
    assert "147,639503" in html and "05/11/2026" in html
    assert "Planilla sintética" in html
    assert pdf.formato_puntos(Decimal("-1234567.5")) == "-1.234.567,500000"


async def test_informe_vacio(caja: AsyncClient, db_session: AsyncSession) -> None:
    esc = await crear_escribano(db_session, "Sin", "Puntos")
    await db_session.commit()
    r = await caja.get(f"/api/v1/previsional/escribanos/{esc.id}/puntos")
    assert r.json()["filas"] == [] and r.json()["total_puntos"] == "0.000000"
    pdf_r = await caja.get(f"/api/v1/previsional/escribanos/{esc.id}/puntos/pdf")
    assert pdf_r.status_code == 200
    import uuid

    no_existe = await caja.get(f"/api/v1/previsional/escribanos/{uuid.uuid4()}/puntos")
    assert no_existe.status_code == 404


async def test_sin_vincular_y_vinculo_manual(
    caja: AsyncClient,
    tesoreria_ac: AsyncClient,
    db_session: AsyncSession,
    operador: User,
    planilla_xlsx: Callable[..., Path],
) -> None:
    luis = await crear_escribano(db_session, "Ejemplo Gómez", "Luis Alberto")
    pedro = await crear_escribano(db_session, "Otro", "Pedro")
    await service.cargar(db_session, leer_planilla(planilla_xlsx()), operador, "P", CTX)
    await db_session.commit()

    sin = await caja.get("/api/v1/previsional/puntos/sin-vincular", params={"page_size": 1})
    aprox = await tesoreria_ac.get(
        "/api/v1/previsional/puntos/sin-vincular", params={"estado": "APROXIMADA"}
    )
    filtrado = await caja.get("/api/v1/previsional/puntos/sin-vincular", params={"q": "nadie"})

    assert sin.status_code == 200
    assert sin.json()["total"] == 2 and len(sin.json()["items"]) == 1
    primero = sin.json()["items"][0]
    assert primero["nombre_origen"] == "FICTICIO Pedro S."
    assert (primero["ejercicios"], primero["primer_anio"], primero["total_puntos"]) == (
        1,
        1991,
        "150.000000",
    )
    assert primero["escribano"] is None
    (aproximado,) = aprox.json()["items"]
    assert aproximado["escribano"]["id"] == str(luis.id)
    assert filtrado.json()["total"] == 0

    # Tesorería consulta pero no vincula.
    negado = await tesoreria_ac.post(
        "/api/v1/previsional/puntos/vincular",
        json={"nombre_origen": "FICTICIO Pedro S.", "escribano_id": str(pedro.id)},
    )
    assert negado.status_code == 403

    ok = await caja.post(
        "/api/v1/previsional/puntos/vincular",
        json={"nombre_origen": "FICTICIO Pedro S.", "escribano_id": str(pedro.id)},
    )
    confirmado = await caja.post(
        "/api/v1/previsional/puntos/vincular",
        json={"nombre_origen": "EJEMPLO GÓMEZ Luis", "escribano_id": str(luis.id)},
    )
    repetido = await caja.post(
        "/api/v1/previsional/puntos/vincular",
        json={"nombre_origen": "FICTICIO Pedro S.", "escribano_id": str(pedro.id)},
    )
    cambio_sin_motivo = await caja.post(
        "/api/v1/previsional/puntos/vincular",
        json={"nombre_origen": "FICTICIO Pedro S.", "escribano_id": str(luis.id)},
    )
    cambio = await caja.post(
        "/api/v1/previsional/puntos/vincular",
        json={
            "nombre_origen": "FICTICIO Pedro S.",
            "escribano_id": str(luis.id),
            "motivo": "Error de vínculo detectado al revisar el legajo",
        },
    )
    inexistente = await caja.post(
        "/api/v1/previsional/puntos/vincular",
        json={"nombre_origen": "NO ESTÁ", "escribano_id": str(luis.id)},
    )

    assert ok.status_code == 200 and ok.json() == {"filas": 1}
    assert confirmado.json() == {"filas": 1}
    assert repetido.status_code == 409
    assert cambio_sin_motivo.status_code == 422
    assert cambio.status_code == 200
    assert inexistente.status_code == 404
    luis_id, pedro_id = luis.id, pedro.id
    db_session.expire_all()
    filas = (
        await db_session.scalars(
            select(PuntosAfiliado).where(PuntosAfiliado.nombre_origen == "FICTICIO Pedro S.")
        )
    ).all()
    assert {(f.escribano_id, f.vinculacion) for f in filas} == {(luis_id, "MANUAL")}
    logs = (
        await db_session.scalars(
            select(AuditSecurityLog)
            .where(AuditSecurityLog.event_type == "PUNTOS_VINCULADOS")
            .order_by(AuditSecurityLog.event_timestamp)
        )
    ).all()
    assert len(logs) == 3
    ultimo = next(
        lg for lg in logs if lg.details and lg.details.get("motivo") and lg.severity == "WARNING"
    )
    assert ultimo.old_value == {
        "vinculos": [{"escribano_id": str(pedro_id), "vinculacion": "MANUAL"}]
    }
    assert ultimo.new_value == {"escribano_id": str(luis_id), "vinculacion": "MANUAL"}
    # Queda solo el nombre que no tiene escribano en el padrón de este test.
    restante = (await caja.get("/api/v1/previsional/puntos/sin-vincular")).json()
    assert [i["nombre_origen"] for i in restante["items"]] == ["PRUEBA Ana Sintética"]


async def test_calculo_deshabilitado(caja: AsyncClient, tesoreria_ac: AsyncClient) -> None:
    estado = await tesoreria_ac.get("/api/v1/previsional/calculo")
    calcular = await caja.post("/api/v1/previsional/ejercicios/2026/calcular")
    sin_permiso = await tesoreria_ac.post("/api/v1/previsional/ejercicios/2026/calcular")

    assert estado.json()["habilitado"] is False
    assert "TODO(negocio)" in estado.json()["motivo"]
    assert calcular.status_code == 501
    assert calcular.headers["content-type"] == "application/problem+json"
    assert calcular.json()["type"] == "urn:suite-notarial:previsional:regla-pendiente"
    assert sin_permiso.status_code == 403


async def test_reporte_por_ejercicio_paridad(
    tesoreria_ac: AsyncClient, cargada: None, db_session: AsyncSession
) -> None:
    pantalla = await tesoreria_ac.get("/api/v1/reportes/PUNTOS_EJERCICIOS", params={"page_size": 1})
    segunda = await tesoreria_ac.get(
        "/api/v1/reportes/PUNTOS_EJERCICIOS", params={"page_size": 1, "page": 2}
    )
    xlsx = await tesoreria_ac.get(
        "/api/v1/reportes/PUNTOS_EJERCICIOS/export", params={"formato": "xlsx"}
    )
    csv_r = await tesoreria_ac.get(
        "/api/v1/reportes/PUNTOS_EJERCICIOS/export", params={"formato": "csv"}
    )
    filtrado = await tesoreria_ac.get(
        "/api/v1/reportes/PUNTOS_EJERCICIOS", params={"anio_desde": "1991", "anio_hasta": "1991"}
    )
    columnas = {
        c["key"]: c
        for c in next(
            r
            for r in (await tesoreria_ac.get("/api/v1/reportes")).json()
            if r["codigo"] == "PUNTOS_EJERCICIOS"
        )["columnas"]
    }

    assert pantalla.status_code == 200, pantalla.text
    body = pantalla.json()
    assert body["total"] == 2
    (fila_91,) = body["items"]
    (fila_90,) = segunda.json()["items"]
    assert fila_91["anio"] == 1991
    assert fila_90["suma_puntos"] == "200.000000"
    assert fila_90["cantidad_afiliados"] == "2.0000"
    assert fila_90["aporte_medio"] == "417.333336"
    assert fila_90["sin_vincular"] == 2
    assert body["totales"] == {
        "total_aportes": "83567.17",
        "suma_aportes": "83567.17",
        "sin_vincular": 4,
    }
    assert (
        columnas["suma_puntos"]["tipo"] == "DECIMAL" and columnas["suma_puntos"]["decimales"] == 6
    )
    assert [f["anio"] for f in filtrado.json()["items"]] == [1991]

    hoja = load_workbook(io.BytesIO(xlsx.content)).active
    assert hoja is not None
    filas_xlsx = list(hoja.iter_rows(min_row=6, max_row=8, values_only=True))
    assert [f[0] for f in filas_xlsx[:2]] == [1991, 1990]
    assert Decimal(str(filas_xlsx[1][7])) == Decimal("200.000000")
    assert Decimal(str(filas_xlsx[2][3])) == Decimal("83567.17")
    assert hoja.cell(row=7, column=8).number_format == "#,##0.000000"
    filas_csv = list(csv.reader(io.StringIO(csv_r.content.decode("utf-8-sig")), delimiter=";"))
    assert filas_csv[2][7] == "200,000000" and filas_csv[2][5] == "2,0000"
    assert filas_csv[-1][3] == "83567,17"


async def test_notario_no_accede_al_reporte(notario_ana: Notario) -> None:
    r = await notario_ana.client.get("/api/v1/reportes/PUNTOS_EJERCICIOS")
    assert r.status_code == 403
