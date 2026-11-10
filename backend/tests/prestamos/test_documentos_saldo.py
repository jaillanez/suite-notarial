"""Documentación de las solicitudes y saldo del conjunto de préstamos (Anexo I).

- La documentación que exige la línea tiene que estar cargada para otorgar; el archivo se valida
  por magic bytes y se verifica contra su huella al descargarlo.
- Nada se borra: un documento cargado por error se anula y deja de contar. Con la solicitud
  resuelta la documentación ya no cambia (también en la base).
- El garante no ve la documentación del titular.
- El saldo del conjunto suma los préstamos vigentes del titular, por moneda.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import anyio
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import get_settings
from app.modules.pagos.storage import upload_root
from app.modules.prestamos.models import DocumentoPrestamo
from tests.ddjj.conftest import Escenario
from tests.pagos.conftest import PDF, png
from tests.prestamos.test_monedas import LINEA_USD
from tests.prestamos.test_prestamos import _otorgado, solicitud

D = Decimal


async def _cargar(
    client: AsyncClient,
    prestamo_id: str,
    tipo: str = "CERTIFICADO_INGRESOS",
    *,
    contenido: bytes = PDF,
    nombre: str = "certificado.pdf",
    descripcion: str | None = None,
) -> Any:
    data = {"tipo": tipo} | ({"descripcion": descripcion} if descripcion else {})
    return await client.post(
        f"/api/v1/prestamos/{prestamo_id}/documentos",
        data=data,
        files={"archivo": (nombre, contenido, "application/pdf")},
    )


async def _eventos(session: AsyncSession, tipo: str) -> list[AuditSecurityLog]:
    filas = await session.scalars(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == tipo)
    )
    return list(filas.all())


@pytest.fixture
async def con_requisitos(
    staff: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> dict[str, Any]:
    """Solicitud del titular en una línea que exige certificado de ingresos y de bienes."""
    linea = await crear_linea(requiere_certificado_ingresos=True, requiere_certificado_bienes=True)
    r = await staff.post("/api/v1/prestamos", json=solicitud(escenario, linea))
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_sin_la_documentacion_requerida_no_se_otorga(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    con_requisitos: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = con_requisitos["id"]
    assert con_requisitos["documentacion_requerida"] == [
        {"tipo": "CERTIFICADO_INGRESOS", "cargado": False},
        {"tipo": "CERTIFICADO_BIENES", "cargado": False},
    ]
    assert "Falta cargar el certificado de ingresos." in con_requisitos["impedimentos_actuales"]
    sin_docs = await admin.post(f"/api/v1/prestamos/{pid}/otorgar")
    assert sin_docs.status_code == 409
    assert "certificado de bienes" in sin_docs.json()["detail"]

    # El titular carga el de ingresos; la Caja, el de bienes (una imagen).
    propio = await _cargar(notario, pid)
    assert propio.status_code == 201, propio.text
    [doc] = propio.json()["documentos"]
    assert doc["subido_por"] == "Vos"
    assert doc["nombre_original"] == "certificado.pdf"
    assert doc["mime_type"] == "application/pdf"
    assert doc["puede_anular"] is True
    assert "archivo" not in doc
    caja = await _cargar(staff, pid, "CERTIFICADO_BIENES", contenido=png(), nombre="bienes.png")
    assert caja.status_code == 201, caja.text
    detalle = caja.json()
    # (Mismo instante en la transacción del test: el orden entre ambos no está definido.)
    assert {d["mime_type"] for d in detalle["documentos"]} == {"application/pdf", "image/png"}
    assert all(r["cargado"] for r in detalle["documentacion_requerida"])
    assert not any("Falta cargar" in i for i in detalle["impedimentos_actuales"])
    # El escribano no ve los correos del personal.
    visto = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    [de_caja] = [d for d in visto["documentos"] if d["tipo"] == "CERTIFICADO_BIENES"]
    assert de_caja["subido_por"] == "Caja Notarial"
    assert de_caja["puede_anular"] is False

    cargados = await _eventos(db_session, "PRESTAMO_DOCUMENTO_CARGADO")
    assert {e.new_value["tipo"] for e in cargados if e.new_value} == {
        "CERTIFICADO_INGRESOS",
        "CERTIFICADO_BIENES",
    }
    assert all(e.new_value and len(e.new_value["sha256"]) == 64 for e in cargados)

    otorgado = await admin.post(f"/api/v1/prestamos/{pid}/otorgar")
    assert otorgado.status_code == 200, otorgado.text
    resuelto = otorgado.json()
    assert resuelto["puede_cargar_documentos"] is False
    assert not any(d["puede_anular"] for d in resuelto["documentos"])
    # Resuelta la solicitud, la documentación no cambia: ni por la API ni en la base.
    assert (await _cargar(staff, pid, "OTRO", descripcion="Tardío")).status_code == 409
    anular = f"/api/v1/prestamos/{pid}/documentos/{doc['id']}/anular"
    assert (await staff.post(anular, json={"motivo": "Ya no sirve"})).status_code == 409
    with pytest.raises(DBAPIError, match="préstamo resuelto"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE prestamos_documentos SET anulado_en = now(), "
                    "anulado_por_user_id = subido_por_user_id, motivo_anulacion = 'x' "
                    "WHERE id = :id"
                ),
                {"id": doc["id"]},
            )


async def test_anular_un_documento_cargado_por_error(
    notario: AsyncClient,
    staff: AsyncClient,
    con_requisitos: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = con_requisitos["id"]
    doc = (await _cargar(notario, pid)).json()["documentos"][0]
    caja = next(
        d
        for d in (await _cargar(staff, pid, "CERTIFICADO_BIENES")).json()["documentos"]
        if d["tipo"] == "CERTIFICADO_BIENES"
    )
    url = f"/api/v1/prestamos/{pid}/documentos/{{}}/anular"

    # El escribano no anula lo que cargó la Caja; el motivo es obligatorio.
    assert (
        await notario.post(url.format(caja["id"]), json={"motivo": "No es mío"})
    ).status_code == 403
    assert (await notario.post(url.format(doc["id"]), json={"motivo": ""})).status_code == 422
    anulado = await notario.post(url.format(doc["id"]), json={"motivo": "Archivo equivocado"})
    assert anulado.status_code == 200, anulado.text
    detalle = anulado.json()
    # Sigue a la vista (no se borra) pero ya no cuenta como cargado.
    [visto] = [d for d in detalle["documentos"] if d["id"] == doc["id"]]
    assert visto["anulado_en"] is not None
    assert visto["motivo_anulacion"] == "Archivo equivocado"
    assert detalle["documentacion_requerida"][0] == {
        "tipo": "CERTIFICADO_INGRESOS",
        "cargado": False,
    }
    otra = await notario.post(url.format(doc["id"]), json={"motivo": "De nuevo"})
    assert otra.status_code == 409

    # La base no deja borrar ni modificar el contenido.
    with pytest.raises(DBAPIError, match=r"no permitido|permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM prestamos_documentos WHERE id = :id"), {"id": caja["id"]}
            )
    with pytest.raises(DBAPIError, match="no se modifica"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE prestamos_documentos SET tipo = 'OTRO' WHERE id = :id"),
                {"id": caja["id"]},
            )
    [evento] = await _eventos(db_session, "PRESTAMO_DOCUMENTO_ANULADO")
    assert evento.new_value == {"anulado": True, "motivo": "Archivo equivocado"}


async def test_archivo_validado_servido_y_verificado(
    notario: AsyncClient,
    staff: AsyncClient,
    tesoreria: AsyncClient,
    con_requisitos: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = con_requisitos["id"]
    falso = await _cargar(notario, pid, contenido=b"MZ ejecutable", nombre="certificado.pdf")
    assert falso.status_code == 415
    assert (await _cargar(notario, pid, "OTRO")).status_code == 422  # sin descripción
    # Tesorería ve los préstamos pero no los administra: no carga documentación.
    assert (await _cargar(tesoreria, pid)).status_code == 403

    doc = (await _cargar(notario, pid)).json()["documentos"][0]
    url = f"/api/v1/prestamos/{pid}/documentos/{doc['id']}/archivo"
    ok = await staff.get(url)
    assert ok.status_code == 200
    assert ok.content == PDF
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert "certificado" not in ok.headers["content-disposition"]

    guardado = await db_session.scalar(select(DocumentoPrestamo))
    assert guardado is not None
    assert guardado.archivo.startswith("prestamos/")
    await anyio.Path(upload_root(get_settings()) / guardado.archivo).write_bytes(PDF + b"%x\n")
    alterado = await notario.get(url)
    assert alterado.status_code == 409
    [critico] = await _eventos(db_session, "PRESTAMO_DOCUMENTO_ALTERADO")
    assert critico.details is not None
    assert critico.details["documento_id"] == doc["id"]


async def test_el_garante_no_ve_la_documentacion_del_titular(
    notario: AsyncClient,
    staff: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    # El adscripto pide un préstamo con el titular (el escribano de la sesión) como garante.
    linea = await crear_linea(requiere_certificado_ingresos=True)
    pedido = await staff.post(
        "/api/v1/prestamos",
        json=solicitud(
            escenario,
            linea,
            escribano_id=str(escenario.adscripto.id),
            garante_escribano_id=str(escenario.titular.id),
        ),
    )
    assert pedido.status_code == 201, pedido.text
    pid = pedido.json()["id"]
    doc = (await _cargar(staff, pid)).json()["documentos"][0]

    visto = await notario.get(f"/api/v1/prestamos/{pid}")
    assert visto.status_code == 200
    assert visto.json()["documentos"] == []
    assert visto.json()["puede_cargar_documentos"] is False
    archivo = await notario.get(f"/api/v1/prestamos/{pid}/documentos/{doc['id']}/archivo")
    assert archivo.status_code == 404
    assert (await _cargar(notario, pid)).status_code == 404


async def test_saldo_del_conjunto_de_prestamos(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    tesoreria: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    vacio = (await notario.get("/api/v1/prestamos/saldo")).json()
    assert vacio["monedas"] == []
    assert vacio["escribano"]["id"] == str(escenario.titular.id)

    linea = await crear_linea()
    otra = await crear_linea(codigo="LINEA_OTRA")
    # Dos préstamos vigentes de $ 100.000 en 12 cuotas de $ 8.884,88, y una solicitud abierta.
    ingreso = {"ingreso_neto": "200000.00"}
    p1 = await _otorgado(staff, admin, solicitud(escenario, linea, **ingreso))
    await _otorgado(staff, admin, solicitud(escenario, otra, **ingreso))
    abierta = await staff.post("/api/v1/prestamos", json=solicitud(escenario, linea, **ingreso))
    assert abierta.status_code == 201, abierta.text
    pagada = await tesoreria.post(
        f"/api/v1/prestamos/{p1['id']}/cuotas/1/pago",
        json={"fecha_pago": "2026-10-23", "importe": "8884.88"},
    )
    assert pagada.status_code == 200, pagada.text

    saldo = (await notario.get("/api/v1/prestamos/saldo")).json()
    assert saldo["solicitudes_pendientes"] == 1
    [pesos] = saldo["monedas"]
    assert pesos["moneda"] == "ARS"
    assert pesos["prestamos_vigentes"] == 2
    segundo_saldo = D(p1["plan"][1]["saldo_inicial"])
    assert D(pesos["saldo_capital"]) == segundo_saldo + D("100000.00")
    assert pesos["cuotas_pendientes"] == 23
    plan = [D(c["cuota"]) for c in p1["plan"]]
    assert D(pesos["total_pendiente"]) == sum(plan[1:]) + sum(plan)
    assert pesos["cuotas_vencidas"] == 0
    # Lo próximo es la cuota 1 del segundo (la del primero ya está pagada).
    assert pesos["proximo_vencimiento"] == "2026-11-23"
    assert D(pesos["importe_proximo_vencimiento"]) == D("8884.88")

    # Meses después hay cuotas vencidas impagas.
    reloj(date(2027, 1, 1))
    atrasado = (await notario.get("/api/v1/prestamos/saldo")).json()["monedas"][0]
    assert atrasado["cuotas_vencidas"] == 3
    assert D(atrasado["importe_vencido"]) == D("8884.88") * 3

    # El personal consulta el de un escribano; el escribano no puede pedir el de otro.
    ajeno = await notario.get(
        "/api/v1/prestamos/saldo", params={"escribano_id": str(escenario.adscripto.id)}
    )
    assert ajeno.json()["escribano"]["id"] == str(escenario.titular.id)
    del_adscripto = await staff.get(
        "/api/v1/prestamos/saldo", params={"escribano_id": str(escenario.adscripto.id)}
    )
    assert del_adscripto.json()["monedas"] == []
    cartera = (await staff.get("/api/v1/prestamos/saldo")).json()
    assert cartera["escribano"] is None
    assert cartera["monedas"][0]["prestamos_vigentes"] >= 2


async def test_saldo_separado_por_moneda(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    linea = await crear_linea(**LINEA_USD)
    await _otorgado(
        staff,
        admin,
        solicitud(escenario, linea, capital="10000.00", ingreso_neto="5000.00"),
    )
    [dolares] = (await notario.get("/api/v1/prestamos/saldo")).json()["monedas"]
    assert dolares["moneda"] == "USD"
    assert D(dolares["saldo_capital"]) == D("10000.00")
