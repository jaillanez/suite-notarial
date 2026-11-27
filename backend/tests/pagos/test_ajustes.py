"""Créditos y débitos sobre boletas (Caja, 26/11/2026): cuatro ojos, saldo de la boleta,
condonación total y pago con centavos de diferencia."""

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from tests.ddjj.conftest import _client
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.pagos.conftest import adjuntar

URL = "/api/v1/ajustes"


@pytest.fixture
async def admin(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


def _credito(boleta: dict[str, Any], importe: str, **extra: Any) -> dict[str, Any]:
    return {
        "boleta_id": boleta["id"],
        "tipo": "CREDITO",
        "concepto": "REDONDEO",
        "importe": importe,
        "justificacion": "Pagó dos centavos de menos por redondeo del banco.",
        **extra,
    }


async def _saldo(client: AsyncClient, boleta: dict[str, Any]) -> str:
    r = await client.get(f"{URL}/boleta/{boleta['numero']}")
    assert r.status_code == 200, r.text
    saldo: str = r.json()["boleta"]["saldo_a_pagar"]
    return saldo


async def test_cuatro_ojos_y_permisos(
    staff: AsyncClient,
    admin: AsyncClient,
    notario: AsyncClient,
    boleta: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    # El escribano no propone ni consulta ajustes.
    assert (await notario.post(URL, json=_credito(boleta, "0.02"))).status_code == 403
    assert (await notario.get(URL)).status_code == 403

    propuesto = await staff.post(URL, json=_credito(boleta, "0.02"))
    assert propuesto.status_code == 201, propuesto.text
    ajuste = propuesto.json()
    assert ajuste["estado"] == "PROPUESTO" and ajuste["puede_resolver"] is False
    # Propuesto todavía no cuenta.
    assert await _saldo(staff, boleta) == boleta["total_a_pagar"]
    # Caja propone, pero no aprueba.
    assert (await staff.post(f"{URL}/{ajuste['id']}/aprobar")).status_code == 403

    # El administrador no aprueba lo que propuso él mismo.
    propio = (await admin.post(URL, json=_credito(boleta, "0.01"))).json()
    assert (await admin.post(f"{URL}/{propio['id']}/aprobar")).status_code == 403
    assert (await admin.get(URL, params={"estado": "PROPUESTO"})).json()["total"] == 2

    aprobado = await admin.post(f"{URL}/{ajuste['id']}/aprobar")
    assert aprobado.status_code == 200, aprobado.text
    assert aprobado.json()["estado"] == "APROBADO"
    assert (await admin.post(f"{URL}/{ajuste['id']}/aprobar")).status_code == 409
    esperado = Decimal(boleta["total_a_pagar"]) - Decimal("0.02")
    assert await _saldo(staff, boleta) == f"{esperado:.2f}"

    # El escribano ve el saldo y el ajuste en su boleta.
    propia = (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()
    assert propia["saldo_a_pagar"] == f"{esperado:.2f}"
    assert [(a["tipo"], a["importe"]) for a in propia["ajustes"]] == [("CREDITO", "0.02")]

    eventos = (
        await db_session.scalars(
            select(AuditSecurityLog.event_type).where(AuditSecurityLog.event_type.like("AJUSTE_%"))
        )
    ).all()
    assert sorted(eventos) == ["AJUSTE_APROBADO", "AJUSTE_PROPUESTO", "AJUSTE_PROPUESTO"]
    # Sin borrado ni edición (INM).
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("DELETE FROM pagos_ajustes"))
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("UPDATE pagos_ajustes SET importe = 1"))


async def test_validaciones(staff: AsyncClient, admin: AsyncClient, boleta: dict[str, Any]) -> None:
    # La condonación y la rebaja de intereses citan la resolución de la Junta.
    sin_resolucion = await staff.post(URL, json=_credito(boleta, "10.00", concepto="CONDONACION"))
    assert sin_resolucion.status_code == 422
    # Un crédito no puede superar lo que queda por pagar.
    de_mas = Decimal(boleta["total_a_pagar"]) + Decimal("0.01")
    assert (await staff.post(URL, json=_credito(boleta, f"{de_mas:.2f}"))).status_code == 422
    corta = await staff.post(URL, json=_credito(boleta, "1.00", justificacion="corto"))
    assert corta.status_code == 422
    # Rechazar exige motivo y queda resuelto.
    ajuste = (await staff.post(URL, json=_credito(boleta, "1.00"))).json()
    rechazado = await admin.post(
        f"{URL}/{ajuste['id']}/rechazar", json={"motivo": "No corresponde el redondeo"}
    )
    assert rechazado.status_code == 200, rechazado.text
    assert rechazado.json()["motivo_rechazo"] == "No corresponde el redondeo"
    assert await _saldo(staff, boleta) == boleta["total_a_pagar"]


async def test_condonacion_total_cancela_la_boleta(
    staff: AsyncClient, admin: AsyncClient, notario: AsyncClient, boleta: dict[str, Any]
) -> None:
    ajuste = (
        await staff.post(
            URL,
            json=_credito(
                boleta,
                boleta["total_a_pagar"],
                concepto="CONDONACION",
                resolucion="Acta Junta 12/2026",
                justificacion="Condonación de la cuota: el escribano no ejerce este período.",
            ),
        )
    ).json()
    assert (await admin.post(f"{URL}/{ajuste['id']}/aprobar")).status_code == 200
    propia = (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()
    assert propia["estado"] == "PAGADA"
    assert propia["saldo_a_pagar"] == "0.00"
    # Pagada, ya no admite ajustes.
    assert (await staff.post(URL, json=_credito(boleta, "1.00"))).status_code == 409


async def test_tesoreria_confirma_el_saldo_con_centavos_de_menos(
    staff: AsyncClient,
    admin: AsyncClient,
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
) -> None:
    pagado = Decimal(boleta["total_a_pagar"]) - Decimal("0.02")
    comprobante = (await adjuntar(notario, boleta, importe=f"{pagado:.2f}")).json()
    url = f"/api/v1/pagos/comprobantes/{comprobante['id']}/aprobar"
    pago = {"importe_confirmado": f"{pagado:.2f}", "fecha_acreditacion": "2026-10-23"}
    # Sin ajuste, no cuadra.
    sin_ajuste = await tesoreria.post(url, json=pago)
    assert sin_ajuste.status_code == 422
    assert "crédito o un débito" in sin_ajuste.json()["detail"]

    ajuste = (await staff.post(URL, json=_credito(boleta, "0.02"))).json()
    assert (await admin.post(f"{URL}/{ajuste['id']}/aprobar")).status_code == 200
    detalle = (await tesoreria.get(f"/api/v1/pagos/comprobantes/{comprobante['id']}")).json()
    assert detalle["diferencia"] == "0.00"
    confirmado = await tesoreria.post(url, json=pago)
    assert confirmado.status_code == 200, confirmado.text
    propia = (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()
    assert propia["estado"] == "PAGADA"


async def test_debito_sube_el_saldo(
    staff: AsyncClient, admin: AsyncClient, boleta: dict[str, Any]
) -> None:
    debito = {**_credito(boleta, "0.03"), "tipo": "DEBITO"}
    debito["justificacion"] = "Pagó tres centavos de más: se imputan a la boleta."
    ajuste = (await staff.post(URL, json=debito)).json()
    assert (await admin.post(f"{URL}/{ajuste['id']}/aprobar")).status_code == 200
    esperado = Decimal(boleta["total_a_pagar"]) + Decimal("0.03")
    assert await _saldo(staff, boleta) == f"{esperado:.2f}"
