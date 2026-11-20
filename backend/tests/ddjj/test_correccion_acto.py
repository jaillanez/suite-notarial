"""Pedidos de la Caja del 20/11/2026: corregir un acto cargado y el «pagar hasta» de la boleta."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from tests.ddjj.conftest import Escenario, escritura
from tests.ddjj.test_protocolo import _agregar, _borrador


async def _corregir(client: AsyncClient, ddjj_id: str, acto_id: str, acto: dict[str, Any]) -> Any:
    return await client.put(f"/api/v1/ddjj/declaraciones/{ddjj_id}/actos/{acto_id}", json=acto)


async def _detalle(client: AsyncClient, ddjj_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/v1/ddjj/declaraciones/{ddjj_id}")).json()
    return body


async def test_corregir_un_acto_lo_reemplaza_y_queda_auditado(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    primero = await _agregar(notario, ddjj["id"], escritura(escenario.titular, 1, "1000", folio=1))
    segundo = await _agregar(notario, ddjj["id"], escritura(escenario.titular, 2, "1000", folio=3))
    assert primero.status_code == segundo.status_code == 201

    # El folio repetido de otra escritura sigue bloqueando al corregir.
    repetido = await _corregir(
        notario, ddjj["id"], segundo.json()["id"], escritura(escenario.titular, 2, "1000", folio=1)
    )
    assert repetido.status_code == 409
    assert "folio 1" in repetido.json()["detail"]
    # Si la corrección no pasa, el acto queda como estaba.
    assert [a["folio"] for a in (await _detalle(notario, ddjj["id"]))["actos"]] == [1, 3]

    corregido = await _corregir(
        notario,
        ddjj["id"],
        segundo.json()["id"],
        escritura(escenario.titular, 2, "2500", folio=2, naturaleza="Donación"),
    )
    assert corregido.status_code == 200, corregido.text
    actos = (await _detalle(notario, ddjj["id"]))["actos"]
    assert [(a["numero_escritura"], a["folio"], a["naturaleza"]) for a in actos] == [
        (1, 1, "Compraventa"),
        (2, 2, "Donación"),
    ]
    eventos = (
        await db_session.scalars(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type.in_(("DDJJ_ACTO_BAJA", "DDJJ_ACTO_AGREGADO"))
            )
        )
    ).all()
    baja = next(e for e in eventos if e.event_type == "DDJJ_ACTO_BAJA")
    assert baja.old_value is not None and baja.old_value["folio"] == 3
    alta = next(
        e for e in eventos if e.details and e.details.get("corrige_acto_id") == segundo.json()["id"]
    )
    assert alta.new_value is not None and alta.new_value["folio"] == 2


async def test_corregir_un_acto_de_otra_ddjj_no_se_puede(
    notario: AsyncClient, escenario: Escenario
) -> None:
    agosto = await _borrador(notario, escenario, "2026-08")
    setiembre = await _borrador(notario, escenario, "2026-09")
    acto = await _agregar(
        notario, agosto["id"], escritura(escenario.titular, 1, "1000", fecha_acto="2026-08-20")
    )
    respuesta = await _corregir(
        notario, setiembre["id"], acto.json()["id"], escritura(escenario.titular, 5, "1000")
    )
    assert respuesta.status_code == 404


async def test_sabado_no_se_carga(notario: AsyncClient, escenario: Escenario) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    sabado = await _agregar(
        notario, ddjj["id"], escritura(escenario.titular, 1, "1000", fecha_acto="2026-09-12")
    )
    assert sabado.status_code == 409
    assert "sábado" in sabado.json()["detail"]


async def test_en_termino_la_boleta_vale_hasta_el_vencimiento(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    await _agregar(notario, ddjj["id"], escritura(escenario.titular, 1, "1000"))
    boletas = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    assert boletas.status_code == 201, boletas.text
    boleta = boletas.json()[0]
    assert boleta["dias_mora"] == 0
    assert boleta["fecha_pago"] == boleta["fecha_vencimiento"] == "2026-10-28"


async def test_una_base_imponible_grande_se_puede_ver(
    notario: AsyncClient, escenario: Escenario
) -> None:
    """La DDJJ de enero del Registro 9999 no abría: el acto se cargó con 14 cifras (lo admite la
    columna) y la respuesta solo aceptaba 13."""
    ddjj = await _borrador(notario, escenario, "2026-09")
    acto = await _agregar(notario, ddjj["id"], escritura(escenario.titular, 1, "10000000000000.00"))
    assert acto.status_code == 201, acto.text
    detalle = await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")
    assert detalle.status_code == 200, detalle.text
    assert detalle.json()["actos"][0]["base_imponible"] == "10000000000000.00"
    planilla = await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/planilla")
    assert planilla.status_code == 200, planilla.text
