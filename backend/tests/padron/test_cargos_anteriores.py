"""Cargos anteriores ya terminados (pedido de la Caja, 23/11/2026): se cargan cerrados, con
fecha desde y hasta, sin pisar otros cargos."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.padron.conftest import Factory


async def _anterior(caja: AsyncClient, escribano_id: str, **datos: Any) -> Any:
    return await caja.post(
        f"/api/v1/padron/escribanos/{escribano_id}/cargos/anteriores", json=datos
    )


async def test_carga_un_cargo_anterior_al_vigente(
    caja: AsyncClient, registro: Factory, escribano: Factory, db_session: AsyncSession
) -> None:
    reg, otro_reg = await registro(), await registro()
    esc = await escribano()
    titular = await caja.post(
        f"/api/v1/padron/escribanos/{esc['id']}/cargos",
        json={"registro_id": reg["id"], "cargo": "TITULAR", "fecha_desde": "2020-06-01"},
    )
    assert titular.status_code == 201

    response = await _anterior(
        caja,
        esc["id"],
        registro_id=otro_reg["id"],
        cargo="ADSCRIPTO",
        fecha_desde="2016-01-10",
        fecha_hasta="2020-06-01",
        resolucion_designacion="Res. 12/2016",
    )

    assert response.status_code == 201, response.text
    cargos = response.json()["cargos"]
    anterior = next(c for c in cargos if c["registro_id"] == otro_reg["id"])
    assert anterior["is_current"] is False
    assert anterior["fecha_hasta"] == "2020-06-01"
    # El titular vigente sigue igual.
    assert sum(1 for c in cargos if c["is_current"]) == 1
    eventos = await db_session.scalars(
        select(AuditSecurityLog.details).where(
            AuditSecurityLog.event_type == "PADRON_CARGO_ASSIGNED"
        )
    )
    assert any((d or {}).get("cargo_anterior") for d in eventos)


async def test_no_pisa_otro_cargo_del_escribano(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg, otro_reg = await registro(), await registro()
    esc = await escribano()
    await caja.post(
        f"/api/v1/padron/escribanos/{esc['id']}/cargos",
        json={"registro_id": reg["id"], "cargo": "TITULAR", "fecha_desde": "2020-06-01"},
    )

    response = await _anterior(
        caja,
        esc["id"],
        registro_id=otro_reg["id"],
        cargo="ADSCRIPTO",
        fecha_desde="2019-01-01",
        fecha_hasta="2021-01-01",
    )

    assert response.status_code == 409
    assert "Se superpone" in response.json()["detail"]


async def test_no_dos_titulares_en_el_mismo_periodo(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    actual, anterior = await escribano(), await escribano()
    await caja.post(
        f"/api/v1/padron/escribanos/{actual['id']}/cargos",
        json={"registro_id": reg["id"], "cargo": "TITULAR", "fecha_desde": "2020-06-01"},
    )

    pisa = await _anterior(
        caja,
        anterior["id"],
        registro_id=reg["id"],
        cargo="TITULAR",
        fecha_desde="2018-01-01",
        fecha_hasta="2021-01-01",
    )
    antes = await _anterior(
        caja,
        anterior["id"],
        registro_id=reg["id"],
        cargo="TITULAR",
        fecha_desde="2018-01-01",
        fecha_hasta="2020-06-01",
    )

    assert pisa.status_code == 409
    assert "ya tenía titular" in pisa.json()["detail"]
    assert antes.status_code == 201


async def test_fechas_invalidas(caja: AsyncClient, registro: Factory, escribano: Factory) -> None:
    reg = await registro()
    esc = await escribano()

    for desde, hasta in (
        ("2020-01-01", "2019-01-01"),  # hasta antes de desde
        ("2020-01-01", "2099-01-01"),  # termina en el futuro
        ("2010-01-01", "2012-01-01"),  # antes del juramento (2015-03-01)
    ):
        response = await _anterior(
            caja,
            esc["id"],
            registro_id=reg["id"],
            cargo="ADSCRIPTO",
            fecha_desde=desde,
            fecha_hasta=hasta,
        )
        assert response.status_code == 422, (desde, hasta, response.text)


async def test_sin_permiso_de_padron_es_403(
    client: AsyncClient, db_session: AsyncSession, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    esc = await escribano()
    escribano_user = await make_user(db_session)
    await login(client, escribano_user)

    response = await _anterior(
        client,
        esc["id"],
        registro_id=reg["id"],
        cargo="ADSCRIPTO",
        fecha_desde="2016-01-01",
        fecha_hasta="2017-01-01",
    )

    assert response.status_code == 403
