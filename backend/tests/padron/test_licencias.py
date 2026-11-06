"""Licencias de escribanos: no cambian la matrícula ni el cargo; sin solapamiento; auditadas."""

import uuid
from datetime import timedelta
from typing import Any

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.common.dates import today_local
from app.modules.padron.models import Escribano, Licencia
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.padron.conftest import Factory


def _url(item: dict[str, Any]) -> str:
    return f"/api/v1/padron/escribanos/{item['id']}"


async def _licencia(caja: AsyncClient, item: dict[str, Any], **datos: Any) -> Any:
    return await caja.post(
        f"{_url(item)}/licencias", json={"motivo": "Licencia por estudios", **datos}
    )


async def _eventos(db_session: AsyncSession, tipo: str) -> list[AuditSecurityLog]:
    result = await db_session.execute(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == tipo)
    )
    return list(result.scalars())


async def test_licencia_vigente_no_toca_matricula_ni_cargo(
    caja: AsyncClient, escribano: Factory, registro: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    reg = await registro()
    cargo = await caja.post(
        f"{_url(item)}/cargos",
        json={"registro_id": reg["id"], "cargo": "TITULAR", "fecha_desde": "2016-01-01"},
    )
    assert cargo.status_code == 201, cargo.text
    desde = (today_local() - timedelta(days=10)).isoformat()

    response = await _licencia(caja, item, fecha_desde=desde, resolucion_respaldo="Res. 12/26")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["estado_matricula"] == "ACTIVO"
    assert body["cargo_actual"] == "TITULAR" and body["registro_actual"] == reg["numero_registro"]
    assert body["en_licencia_desde"] == desde
    [lic] = body["licencias"]
    assert lic["vigente"] is True and lic["fecha_hasta"] is None
    assert lic["resolucion_respaldo"] == "Res. 12/26"
    # El listado muestra la licencia vigente.
    listado = await caja.get("/api/v1/padron/escribanos", params={"q": item["apellido_nombre"]})
    fila = next(i for i in listado.json()["items"] if i["id"] == item["id"])
    assert fila["en_licencia_desde"] == desde
    [audit] = await _eventos(db_session, "PADRON_LICENCIA_INICIADA")
    assert audit.new_value is not None and audit.new_value["fecha_desde"] == desde
    assert audit.details is not None and audit.details["escribano_id"] == item["id"]


async def test_terminar_y_volver_a_tomar_licencia(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    primera = (await _licencia(caja, item, fecha_desde="2020-01-10")).json()["licencias"][0]

    # Mientras está abierta, otra superpuesta se rechaza.
    superpuesta = await _licencia(caja, item, fecha_desde="2021-05-01", fecha_hasta="2021-06-01")
    assert superpuesta.status_code == 409
    assert "superpone" in superpuesta.json()["detail"]

    fin = await caja.post(
        f"/api/v1/padron/licencias/{primera['id']}/fin", json={"fecha_hasta": "2020-12-31"}
    )
    assert fin.status_code == 200, fin.text
    assert fin.json()["en_licencia_desde"] is None
    assert fin.json()["licencias"][0]["fecha_hasta"] == "2020-12-31"
    # Se puede adelantar, no extender (una prórroga es otra licencia).
    extender = await caja.post(
        f"/api/v1/padron/licencias/{primera['id']}/fin", json={"fecha_hasta": "2021-01-31"}
    )
    assert extender.status_code == 409
    antes_de_empezar = await caja.post(
        f"/api/v1/padron/licencias/{primera['id']}/fin", json={"fecha_hasta": "2019-01-01"}
    )
    assert antes_de_empezar.status_code == 422

    # Vuelve a tomar licencia después de regresar: no se superpone.
    segunda = await _licencia(caja, item, fecha_desde="2021-05-01", fecha_hasta="2021-06-01")
    assert segunda.status_code == 201, segunda.text
    assert [lic["fecha_desde"] for lic in segunda.json()["licencias"]] == [
        "2021-05-01",
        "2020-01-10",
    ]
    [audit] = await _eventos(db_session, "PADRON_LICENCIA_TERMINADA")
    assert audit.old_value is not None and audit.old_value["fecha_hasta"] is None
    assert audit.new_value is not None and audit.new_value["fecha_hasta"] == "2020-12-31"


async def test_reglas_de_fechas_y_estado(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()  # juró el 2015-03-01
    antes = await _licencia(caja, item, fecha_desde="2014-01-01", fecha_hasta="2014-02-01")
    assert antes.status_code == 422 and "juramento" in antes.json()["detail"]
    invertidas = await _licencia(caja, item, fecha_desde="2020-02-01", fecha_hasta="2020-01-01")
    assert invertidas.status_code == 422
    sin_motivo = await caja.post(f"{_url(item)}/licencias", json={"fecha_desde": "2020-01-01"})
    assert sin_motivo.status_code == 422

    # Sin fecha de juramento conocida, no se controla contra ella.
    await db_session.execute(
        update(Escribano)
        .where(Escribano.id == uuid.UUID(item["id"]))
        .values(fecha_matriculacion=None)
    )
    await db_session.flush()
    db_session.expire_all()
    vieja = await _licencia(caja, item, fecha_desde="2014-01-01", fecha_hasta="2014-02-01")
    assert vieja.status_code == 201, vieja.text
    # Y una vez cargada la licencia, el juramento no puede quedar después.
    tarde = await caja.post(f"{_url(item)}/completar", json={"fecha_matriculacion": "2014-06-01"})
    assert tarde.status_code == 422


async def test_quien_ya_no_ejerce_no_tiene_licencia_vigente(
    caja: AsyncClient, escribano: Factory
) -> None:
    item = await escribano()
    baja = await caja.post(
        f"{_url(item)}/estado",
        json={
            "nuevo_estado": "JUBILADO",
            "motivo": "Jubilación ordinaria",
            "fecha_efectiva": "2024-01-01",
        },
    )
    assert baja.status_code == 200, baja.text
    vigente = await _licencia(caja, item, fecha_desde="2024-06-01")
    assert vigente.status_code == 409
    # Una licencia pasada (con regreso) sí se registra como historia.
    pasada = await _licencia(caja, item, fecha_desde="2019-01-01", fecha_hasta="2019-03-01")
    assert pasada.status_code == 201, pasada.text
    assert pasada.json()["en_licencia_desde"] is None


async def test_anular_queda_en_la_historia(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    lic = (await _licencia(caja, item, fecha_desde="2022-01-01")).json()["licencias"][0]

    corto = await caja.post(f"/api/v1/padron/licencias/{lic['id']}/anulacion", json={"motivo": "x"})
    assert corto.status_code == 422
    anulada = await caja.post(
        f"/api/v1/padron/licencias/{lic['id']}/anulacion",
        json={"motivo": "Cargada por error en otro escribano"},
    )
    assert anulada.status_code == 200, anulada.text
    [historia] = anulada.json()["licencias"]
    assert historia["anulada"] is True and historia["vigente"] is False
    assert historia["motivo_anulacion"] == "Cargada por error en otro escribano"
    assert anulada.json()["en_licencia_desde"] is None
    otra_vez = await caja.post(
        f"/api/v1/padron/licencias/{lic['id']}/anulacion", json={"motivo": "De nuevo, por error"}
    )
    assert otra_vez.status_code == 409
    fin = await caja.post(
        f"/api/v1/padron/licencias/{lic['id']}/fin", json={"fecha_hasta": "2022-06-01"}
    )
    assert fin.status_code == 409
    # Anulada, no bloquea otra licencia en las mismas fechas.
    misma = await _licencia(caja, item, fecha_desde="2022-01-01", fecha_hasta="2022-03-01")
    assert misma.status_code == 201, misma.text
    [audit] = await _eventos(db_session, "PADRON_LICENCIA_ANULADA")
    assert audit.old_value is not None and audit.old_value["anulada"] is False
    assert audit.new_value is not None and audit.new_value["anulada"] is True


async def test_inexistentes(caja: AsyncClient) -> None:
    falso = uuid.uuid4()
    lic = await caja.post(
        f"/api/v1/padron/escribanos/{falso}/licencias",
        json={"fecha_desde": "2022-01-01", "motivo": "Licencia por estudios"},
    )
    assert lic.status_code == 404
    fin = await caja.post(
        f"/api/v1/padron/licencias/{falso}/fin", json={"fecha_hasta": "2022-01-01"}
    )
    assert fin.status_code == 404


async def test_licencias_requieren_permiso_de_escritura(
    client: AsyncClient, db_session: AsyncSession, escribano: Factory, caja: AsyncClient
) -> None:
    item = await escribano()
    lic = (await _licencia(caja, item, fecha_desde="2022-01-01")).json()["licencias"][0]
    client.cookies.clear()
    secret = pyotp.random_base32()
    auditor = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    await login(client, auditor, secret)

    assert (await client.get(_url(item))).status_code == 200  # lectura sí
    nueva = await client.post(
        f"{_url(item)}/licencias", json={"fecha_desde": "2023-01-01", "motivo": "Sin permiso"}
    )
    assert nueva.status_code == 403
    fin = await client.post(
        f"/api/v1/padron/licencias/{lic['id']}/fin", json={"fecha_hasta": "2022-02-01"}
    )
    assert fin.status_code == 403
    anular = await client.post(
        f"/api/v1/padron/licencias/{lic['id']}/anulacion", json={"motivo": "Sin permiso alguno"}
    )
    assert anular.status_code == 403


async def test_la_base_impide_solapamiento_y_borrado(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    await _licencia(caja, item, fecha_desde="2022-01-01", fecha_hasta="2022-12-31")
    eid = uuid.UUID(item["id"])
    async with db_session.begin_nested():
        db_session.add(
            Licencia(
                escribano_id=eid,
                fecha_desde=today_local().replace(year=2022, month=6, day=1),
                motivo="Superpuesta directa en la base",
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM padron_licencias WHERE escribano_id = :e"), {"e": eid}
            )


async def test_ficha_con_historia_completa_de_cargos_y_designaciones(
    caja: AsyncClient, escribano: Factory, registro: Factory
) -> None:
    item = await escribano()
    viejo, nuevo = await registro(), await registro()
    adscripto = await caja.post(
        f"{_url(item)}/cargos",
        json={"registro_id": viejo["id"], "cargo": "ADSCRIPTO", "fecha_desde": "2016-01-01"},
    )
    assert adscripto.status_code == 201, adscripto.text
    cerrado = await caja.post(
        f"/api/v1/padron/cargos/{adscripto.json()['cargos'][0]['id']}/cierre",
        json={"fecha_hasta": "2019-12-31", "motivo": "Pasa a titular de otro registro"},
    )
    assert cerrado.status_code == 200, cerrado.text
    titular = await caja.post(
        f"{_url(item)}/cargos",
        json={"registro_id": nuevo["id"], "cargo": "TITULAR", "fecha_desde": "2020-01-01"},
    )
    assert titular.status_code == 201, titular.text

    ficha = (await caja.get(_url(item))).json()
    assert [(c["cargo"], c["numero_registro"], c["fecha_hasta"]) for c in ficha["cargos"]] == [
        ("TITULAR", nuevo["numero_registro"], None),
        ("ADSCRIPTO", viejo["numero_registro"], "2019-12-31"),
    ]
    assert ficha["designaciones_a_cargo"] == []
