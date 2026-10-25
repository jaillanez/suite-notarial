"""Comprobantes y conciliación: adjuntar no es pagar; solo Tesorería confirma (regla PAGO)."""

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
from app.modules.pagos import service as pagos_service
from app.modules.pagos.models import Comprobante, Conciliacion
from app.modules.pagos.storage import upload_root
from tests.conftest import FakeMailer
from tests.ddjj.conftest import HOY
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.pagos.conftest import PDF, adjuntar, png


async def _eventos(db_session: AsyncSession) -> list[str]:
    return list(
        (
            await db_session.scalars(
                select(AuditSecurityLog.event_type).order_by(AuditSecurityLog.event_timestamp)
            )
        ).all()
    )


async def test_adjuntar_no_es_pagar(
    notario: AsyncClient, boleta: dict[str, Any], db_session: AsyncSession
) -> None:
    response = await adjuntar(notario, boleta, contenido=png(), nombre="foto.png", tipo="image/png")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["estado"] == "PENDIENTE_REVISION"
    assert body["boleta"]["estado"] == "PENDIENTE"
    assert body["mime_type"] == "image/png"
    assert body["diferencia"] == "0.00"
    guardado = await db_session.scalar(select(Comprobante))
    assert guardado is not None
    ruta = upload_root(get_settings()) / guardado.archivo
    assert ruta.is_file()
    assert ruta.name.endswith(".png") and "foto" not in ruta.name
    assert oct(ruta.stat().st_mode & 0o777) == "0o600"
    assert "COMPROBANTE_ADJUNTADO" in await _eventos(db_session)
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{boleta['ddjj_id']}")).json()
    assert detalle["boletas"][0]["estado"] == "PENDIENTE"
    assert detalle["boletas"][0]["comprobante"]["estado"] == "PENDIENTE_REVISION"


@pytest.mark.parametrize(
    ("contenido", "nombre", "tipo"),
    [
        (b"#!/bin/sh\nrm -rf /\n", "comprobante.pdf", "application/pdf"),
        (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00", "comprobante.jpg", "image/jpeg"),
        (b"<?php system($_GET['c']); ?>", "comprobante.png", "image/png"),
        (b"<html><script>alert(1)</script></html>", "comprobante.pdf", "application/pdf"),
    ],
)
async def test_extension_falsa_rechazada(
    notario: AsyncClient,
    boleta: dict[str, Any],
    db_session: AsyncSession,
    contenido: bytes,
    nombre: str,
    tipo: str,
) -> None:
    antes = set(upload_root(get_settings()).rglob("*"))

    response = await adjuntar(notario, boleta, contenido=contenido, nombre=nombre, tipo=tipo)

    assert response.status_code == 415
    assert response.headers["content-type"] == "application/problem+json"
    assert await db_session.scalar(select(Comprobante)) is None
    assert set(upload_root(get_settings()).rglob("*")) == antes


async def test_tamano_y_archivo_vacio(notario: AsyncClient, boleta: dict[str, Any]) -> None:
    grande = PDF + b"0" * (10 * 1024 * 1024)

    assert (await adjuntar(notario, boleta, contenido=grande)).status_code == 413
    assert (await adjuntar(notario, boleta, contenido=b"")).status_code == 422


async def test_validaciones_de_carga(notario: AsyncClient, boleta: dict[str, Any]) -> None:
    futura = await adjuntar(notario, boleta, fecha="2026-10-24")
    anterior = await adjuntar(notario, boleta, fecha="2026-10-01")
    ok = await adjuntar(notario, boleta)
    otra = await adjuntar(notario, boleta)

    assert futura.status_code == 422
    assert anterior.status_code == 422
    assert ok.status_code == 201
    assert otra.status_code == 409  # ya hay uno en revisión


async def test_tesoreria_confirma_el_pago(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    db_session: AsyncSession,
    mailer: FakeMailer,
) -> None:
    comprobante = (await adjuntar(notario, boleta)).json()
    mesa = (await tesoreria.get("/api/v1/pagos/comprobantes")).json()
    url = f"/api/v1/pagos/comprobantes/{comprobante['id']}/aprobar"

    distinto = await tesoreria.post(
        url, json={"importe_confirmado": "1000.00", "fecha_acreditacion": "2026-10-23"}
    )
    response = await tesoreria.post(
        url,
        json={
            "importe_confirmado": boleta["total_a_pagar"],
            "fecha_acreditacion": "2026-10-23",
            "identificador_extracto": "EXT-2026-10-23-0042",
        },
    )

    assert [c["id"] for c in mesa["items"]] == [comprobante["id"]]
    assert distinto.status_code == 422
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["estado"] == "APROBADO"
    assert body["boleta"]["estado"] == "PAGADA"
    assert body["conciliacion"]["resultado"] == "APROBADO"
    assert body["conciliacion"]["importe_confirmado"] == boleta["total_a_pagar"]
    asiento = await db_session.scalar(select(Conciliacion))
    assert asiento is not None and asiento.identificador_extracto == "EXT-2026-10-23-0042"
    eventos = await _eventos(db_session)
    assert "COMPROBANTE_APROBADO" in eventos and "BOLETA_PAGADA" in eventos
    assert mailer.sent[-1].subject == f"Pago confirmado · Boleta N° {boleta['numero']}"
    verificacion = (
        await notario.get(f"/api/v1/boletas/verificar/{boleta['codigo_verificacion']}")
    ).json()
    assert verificacion["estado"] == "PAGADA"
    # Ya paga: no admite otro comprobante ni otra boleta.
    assert (await adjuntar(notario, boleta)).status_code == 409
    nueva = await notario.post(
        f"/api/v1/ddjj/declaraciones/{boleta['ddjj_id']}/boletas",
        json={"fecha_pago": "2026-10-30"},
    )
    assert nueva.status_code == 409


async def test_rechazo_con_motivo_avisa_al_escribano(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    mailer: FakeMailer,
) -> None:
    comprobante = (await adjuntar(notario, boleta, importe="1000.00")).json()
    url = f"/api/v1/pagos/comprobantes/{comprobante['id']}/rechazar"

    sin_motivo = await tesoreria.post(url, json={"motivo": "no"})
    response = await tesoreria.post(url, json={"motivo": "El importe no coincide con la boleta."})

    esperado = Decimal("1000.00") - Decimal(boleta["total_a_pagar"])
    assert comprobante["diferencia"] == f"{esperado:.2f}"
    assert sin_motivo.status_code == 422
    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "RECHAZADO"
    assert body["boleta"]["estado"] == "PENDIENTE"
    assert body["motivo_rechazo"] == "El importe no coincide con la boleta."
    mail = mailer.sent[-1]
    assert "El importe no coincide con la boleta." in mail.text
    assert f"https://suite.cajanotarial-sj.test/ddjj/{boleta['ddjj_id']}" in mail.text
    # El escribano no ve el correo de quien rechazó.
    visto = (await notario.get(f"/api/v1/pagos/comprobantes/{comprobante['id']}")).json()
    assert visto["conciliacion"]["operador"] == "Tesorería"
    # Puede adjuntar uno nuevo; uno ya revisado no se vuelve a revisar.
    assert (await adjuntar(notario, boleta)).status_code == 201
    assert (await tesoreria.post(url, json={"motivo": "Segundo intento"})).status_code == 409


async def test_acreditacion_fuera_de_plazo_exige_constancia(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    comprobante = (await adjuntar(notario, boleta)).json()
    monkeypatch.setattr(pagos_service, "today_local", lambda: HOY + timedelta(days=5))
    url = f"/api/v1/pagos/comprobantes/{comprobante['id']}/aprobar"
    datos = {"importe_confirmado": boleta["total_a_pagar"], "fecha_acreditacion": "2026-10-27"}

    sin_constancia = await tesoreria.post(url, json=datos)
    antes_de_transferir = await tesoreria.post(
        url, json={**datos, "fecha_acreditacion": "2026-10-22"}
    )
    con_constancia = await tesoreria.post(
        url, json={**datos, "observaciones": "Transferencia acreditada con demora bancaria."}
    )

    assert sin_constancia.status_code == 422
    assert antes_de_transferir.status_code == 422
    assert con_constancia.status_code == 200


async def test_permisos(
    notario: AsyncClient,
    staff: AsyncClient,
    client: AsyncClient,
    boleta: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    comprobante = (await adjuntar(notario, boleta)).json()
    aprobar = f"/api/v1/pagos/comprobantes/{comprobante['id']}/aprobar"
    datos = {"importe_confirmado": boleta["total_a_pagar"], "fecha_acreditacion": "2026-10-23"}
    otro = await make_user(db_session)
    await login(client, otro)

    assert (await notario.post(aprobar, json=datos)).status_code == 403
    assert (await staff.post(aprobar, json=datos)).status_code == 403  # la Caja no concilia
    assert (await notario.get("/api/v1/pagos/comprobantes")).status_code == 403
    # Un escribano ajeno no ve ni adjunta.
    assert (await client.get(f"/api/v1/pagos/comprobantes/{comprobante['id']}")).status_code == 404
    archivo = await client.get(f"/api/v1/pagos/comprobantes/{comprobante['id']}/archivo")
    assert archivo.status_code == 404
    assert (await adjuntar(client, boleta)).status_code == 404


async def test_mientras_se_revisa_no_se_cambia_la_boleta(
    notario: AsyncClient, boleta: dict[str, Any]
) -> None:
    await adjuntar(notario, boleta)
    ddjj = boleta["ddjj_id"]

    nueva = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj}/boletas", json={"fecha_pago": "2026-10-30"}
    )
    rectificar = await notario.post(f"/api/v1/ddjj/declaraciones/{ddjj}/rectificar")

    assert nueva.status_code == 409
    assert rectificar.status_code == 409


async def test_archivo_servido_y_alterado(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    comprobante = (await adjuntar(notario, boleta)).json()
    url = f"/api/v1/pagos/comprobantes/{comprobante['id']}/archivo"

    ok = await tesoreria.get(url)
    guardado = await db_session.scalar(select(Comprobante))
    assert guardado is not None
    ruta = anyio.Path(upload_root(get_settings()) / guardado.archivo)
    await ruta.write_bytes(PDF + b"% alterado\n")
    alterado = await tesoreria.get(url)

    assert ok.status_code == 200
    assert ok.content == PDF
    assert ok.headers["content-type"] == "application/pdf"
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert "transferencia" not in ok.headers["content-disposition"]
    assert alterado.status_code == 409
    critico = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "COMPROBANTE_ALTERADO")
    )
    assert critico is not None and critico.severity == "CRITICAL"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ddjj_boletas SET estado = 'PAGADA'",
        "UPDATE pagos_comprobantes SET importe_declarado = 1",
        "DELETE FROM pagos_comprobantes",
        "TRUNCATE pagos_comprobantes CASCADE",
    ],
)
async def test_reglas_en_la_base(
    notario: AsyncClient,
    boleta: dict[str, Any],
    db_session: AsyncSession,
    statement: str,
) -> None:
    await adjuntar(notario, boleta)

    with pytest.raises(
        DBAPIError, match=r"conciliación aprobada|no se modifica|permission denied|no permitido"
    ):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_un_asiento_no_se_modifica(
    notario: AsyncClient, tesoreria: AsyncClient, boleta: dict[str, Any], db_session: AsyncSession
) -> None:
    comprobante = (await adjuntar(notario, boleta)).json()
    await tesoreria.post(
        f"/api/v1/pagos/comprobantes/{comprobante['id']}/rechazar",
        json={"motivo": "Comprobante ilegible."},
    )

    for statement in (
        "UPDATE pagos_conciliaciones SET observaciones = 'x'",
        "DELETE FROM pagos_conciliaciones",
        "UPDATE pagos_comprobantes SET estado = 'APROBADO', motivo_rechazo = NULL",
    ):
        with pytest.raises(DBAPIError, match=r"permission denied|no se modifica"):
            async with db_session.begin_nested():
                await db_session.execute(text(statement))
