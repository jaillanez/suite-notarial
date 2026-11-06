"""Primera escritura (antigüedad) e historia del domicilio de los registros."""

import uuid
from datetime import date, timedelta
from typing import Any

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.common.dates import today_local
from app.modules.padron.models import DomicilioRegistro
from app.modules.padron.service import antiguedad
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.padron.conftest import Factory

PRIMERA = {"fecha": "2016-04-12", "numero": "15", "registro": 33, "folio": "120"}


def _url(item: dict[str, Any]) -> str:
    return f"/api/v1/padron/escribanos/{item['id']}"


async def _evento(db_session: AsyncSession, tipo: str) -> AuditSecurityLog:
    result = await db_session.execute(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == tipo)
    )
    return result.scalar_one()


def test_antiguedad_calendario() -> None:
    assert antiguedad(date(2016, 4, 12), date(2026, 11, 6)) == (10, 6)
    assert antiguedad(date(2016, 4, 12), date(2026, 4, 11)) == (9, 11)
    assert antiguedad(date(2016, 4, 12), date(2026, 4, 12)) == (10, 0)
    assert antiguedad(date(2026, 12, 1), date(2026, 11, 6)) == (0, 0)


# --------------------------------------------------------------------------- primera escritura


async def test_primera_escritura_a_completar_y_cargada_desde_completar(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    assert item["a_completar"] == ["primera_escritura"]
    assert item["primera_escritura"] is None and item["antiguedad"] is None

    response = await caja.post(f"{_url(item)}/completar", json={"primera_escritura": PRIMERA})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["a_completar"] == []
    pe = body["primera_escritura"]
    assert (pe["fecha"], pe["numero"], pe["registro"], pe["folio"]) == (
        "2016-04-12",
        "15",
        33,
        "120",
    )
    assert pe["cargada_por"] is not None and pe["cargada_en"] is not None
    anios, meses = antiguedad(date(2016, 4, 12), today_local())
    assert body["antiguedad"] == {"desde": "2016-04-12", "anios": anios, "meses": meses}
    audit = await _evento(db_session, "PADRON_ESCRIBANO_COMPLETADO")
    assert audit.details is not None and audit.details["campos"] == ["primera_escritura"]
    assert audit.new_value is not None and audit.new_value["primera_escritura_registro"] == 33

    # Ya cargada: por «Completar datos» no se cambia.
    otra = await caja.post(f"{_url(item)}/completar", json={"primera_escritura": PRIMERA})
    assert otra.status_code == 409


async def test_correccion_con_motivo_y_auditada(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    carga = await caja.put(f"{_url(item)}/primera-escritura", json=PRIMERA)
    assert carga.status_code == 200, carga.text
    cargada = await _evento(db_session, "PADRON_PRIMERA_ESCRITURA_CARGADA")
    assert cargada.old_value is not None and cargada.old_value["primera_escritura_fecha"] is None

    sin_motivo = await caja.put(f"{_url(item)}/primera-escritura", json={**PRIMERA, "numero": "16"})
    assert sin_motivo.status_code == 422
    igual = await caja.put(
        f"{_url(item)}/primera-escritura", json={**PRIMERA, "motivo": "Revisión del legajo"}
    )
    assert igual.status_code == 409
    corregida = await caja.put(
        f"{_url(item)}/primera-escritura",
        json={**PRIMERA, "numero": "16", "folio": None, "motivo": "Error de tipeo en el número"},
    )
    assert corregida.status_code == 200, corregida.text
    assert corregida.json()["primera_escritura"]["numero"] == "16"
    assert corregida.json()["primera_escritura"]["folio"] is None
    audit = await _evento(db_session, "PADRON_PRIMERA_ESCRITURA_CORREGIDA")
    assert audit.old_value is not None and audit.old_value["primera_escritura_numero"] == "15"
    assert audit.new_value is not None and audit.new_value["primera_escritura_numero"] == "16"
    assert audit.details is not None
    assert audit.details["motivo"] == "Error de tipeo en el número"


async def test_validaciones_de_la_primera_escritura(caja: AsyncClient, escribano: Factory) -> None:
    item = await escribano()  # juró el 2015-03-01
    url = f"{_url(item)}/primera-escritura"
    antes = await caja.put(url, json={**PRIMERA, "fecha": "2014-12-31"})
    assert antes.status_code == 422 and "juramento" in antes.json()["detail"]
    futura = (today_local() + timedelta(days=1)).isoformat()
    assert (await caja.put(url, json={**PRIMERA, "fecha": futura})).status_code == 422
    assert (await caja.put(url, json={**PRIMERA, "registro": 0})).status_code == 422
    assert (await caja.put(url, json={**PRIMERA, "numero": "x" * 21})).status_code == 422
    assert (await caja.put(url, json={"fecha": "2016-01-01"})).status_code == 422
    # El registro puede ser uno que no existe en la Suite (cerrado hace años).
    ok = await caja.put(url, json={**PRIMERA, "registro": 99_999})
    assert ok.status_code == 200, ok.text
    # Con la primera escritura cargada, el juramento no puede quedar después.
    assert (
        await caja.patch(_url(item), json={"fecha_matriculacion": "2017-01-01"})
    ).status_code == 422


async def test_primera_escritura_requiere_permiso(
    client: AsyncClient, db_session: AsyncSession, escribano: Factory
) -> None:
    item = await escribano()
    client.cookies.clear()
    secret = pyotp.random_base32()
    auditor = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    await login(client, auditor, secret)
    response = await client.put(f"{_url(item)}/primera-escritura", json=PRIMERA)
    assert response.status_code == 403


# --------------------------------------------------------------------------- domicilios


async def test_alta_de_registro_abre_su_historia_de_domicilio(
    caja: AsyncClient, registro: Factory
) -> None:
    reg = await registro(fecha_creacion="2001-05-02")
    detalle = (await caja.get(f"/api/v1/padron/registros/{reg['id']}")).json()
    [actual] = detalle["domicilios"]
    assert (actual["domicilio"], actual["fecha_desde"], actual["fecha_hasta"]) == (
        "Calle de Prueba 123",
        "2001-05-02",
        None,
    )
    assert actual["cargado_por"] is not None


async def test_cambiar_domicilio_cierra_el_anterior(
    caja: AsyncClient, registro: Factory, db_session: AsyncSession
) -> None:
    reg = await registro(fecha_creacion="2001-05-02")
    url = f"/api/v1/padron/registros/{reg['id']}/domicilio"

    response = await caja.post(
        url, json={"domicilio": "Av. Libertador 450", "fecha_desde": "2020-03-01"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["domicilio_legal"] == "Av. Libertador 450"
    assert [(d["domicilio"], d["fecha_desde"], d["fecha_hasta"]) for d in body["domicilios"]] == [
        ("Av. Libertador 450", "2020-03-01", None),
        ("Calle de Prueba 123", "2001-05-02", "2020-02-29"),
    ]
    audit = await _evento(db_session, "PADRON_REGISTRO_DOMICILIO_CAMBIADO")
    assert audit.old_value is not None and audit.old_value["domicilio"] == "Calle de Prueba 123"
    assert audit.new_value is not None and audit.new_value["fecha_desde"] == "2020-03-01"
    filas = (
        await db_session.execute(
            select(DomicilioRegistro).where(DomicilioRegistro.registro_id == uuid.UUID(reg["id"]))
        )
    ).scalars()
    assert len(list(filas)) == 2  # nada se borra

    # Reglas: misma dirección, fecha no posterior a la vigente, fecha futura.
    mismo = await caja.post(
        url, json={"domicilio": "Av. Libertador 450", "fecha_desde": "2021-01-01"}
    )
    assert mismo.status_code == 409
    previa = await caja.post(url, json={"domicilio": "Otra calle 1", "fecha_desde": "2020-03-01"})
    assert previa.status_code == 422
    futura = (today_local() + timedelta(days=1)).isoformat()
    assert (
        await caja.post(url, json={"domicilio": "Otra calle 1", "fecha_desde": futura})
    ).status_code == 422


async def test_la_edicion_general_no_cambia_el_domicilio(
    caja: AsyncClient, registro: Factory
) -> None:
    reg = await registro()
    url = f"/api/v1/padron/registros/{reg['id']}"
    distinto = await caja.patch(url, json={"domicilio_legal": "Calle Nueva 9"})
    assert distinto.status_code == 409 and "Cambiar domicilio" in distinto.json()["detail"]
    # El mismo domicilio junto con otros cambios no molesta.
    igual = await caja.patch(
        url, json={"domicilio_legal": "Calle de Prueba 123", "telefono": "264 4000000"}
    )
    assert igual.status_code == 200, igual.text


async def test_domicilio_de_registro_cerrado_o_inexistente(
    caja: AsyncClient, registro: Factory
) -> None:
    reg = await registro()
    cierre = await caja.post(
        f"/api/v1/padron/registros/{reg['id']}/cierre", json={"motivo": "Registro suprimido"}
    )
    assert cierre.status_code == 200, cierre.text
    cerrado = await caja.post(
        f"/api/v1/padron/registros/{reg['id']}/domicilio",
        json={"domicilio": "Calle 2", "fecha_desde": "2024-01-01"},
    )
    assert cerrado.status_code == 409
    inexistente = await caja.post(
        f"/api/v1/padron/registros/{uuid.uuid4()}/domicilio",
        json={"domicilio": "Calle 2", "fecha_desde": "2024-01-01"},
    )
    assert inexistente.status_code == 404


async def test_cambiar_domicilio_requiere_permiso(
    client: AsyncClient, db_session: AsyncSession, registro: Factory
) -> None:
    reg = await registro()
    client.cookies.clear()
    secret = pyotp.random_base32()
    auditor = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    await login(client, auditor, secret)
    response = await client.post(
        f"/api/v1/padron/registros/{reg['id']}/domicilio",
        json={"domicilio": "Calle 2", "fecha_desde": "2024-01-01"},
    )
    assert response.status_code == 403
