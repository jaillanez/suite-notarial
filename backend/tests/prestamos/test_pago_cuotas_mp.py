"""Pago de cuotas de préstamo con Mercado Pago: el escribano paga la próxima cuota, Mercado Pago
la aprueba y la cuota recién pasa a pagada cuando Tesorería confirma el cobro (regla PAGO).
Mercado Pago se simula como en los tests de boletas."""

# ruff: noqa: F811

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import get_settings
from app.modules.pagos.models import PagoMercadoPago
from app.modules.prestamos.models import CuotaPrestamo
from tests.ddjj.conftest import Escenario
from tests.pagos.test_mercadopago import MercadoPagoFalso, mp  # noqa: F401 - fixture
from tests.prestamos.test_monedas import LINEA_USD
from tests.prestamos.test_prestamos import _otorgado, solicitud

D = Decimal


async def _pagar(notario: AsyncClient, prestamo_id: str) -> Any:
    return await notario.post(f"/api/v1/prestamos/{prestamo_id}/mercadopago")


async def _cobrado(
    notario: AsyncClient, mp: MercadoPagoFalso, prestamo_id: str, **pago: Any
) -> tuple[str, dict[str, Any]]:
    """Inicia el cobro de la próxima cuota, Mercado Pago lo aprueba y el escribano vuelve."""
    r = await _pagar(notario, prestamo_id)
    assert r.status_code == 201, r.text
    referencia = mp.cobros[-1]["referencia"]
    mp.informar(referencia, **{"transaction_amount": mp.cobros[-1]["importe"], **pago})
    vuelta = await notario.post(f"/api/v1/pagos/mercadopago/{referencia}/sincronizar")
    assert vuelta.status_code == 200, vuelta.text
    body: dict[str, Any] = vuelta.json()
    return referencia, body


async def _eventos(session: AsyncSession, tipo: str) -> list[AuditSecurityLog]:
    filas = await session.scalars(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == tipo)
    )
    return list(filas.all())


@pytest.fixture
async def prestamo(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> dict[str, Any]:
    """Préstamo vigente del titular: 12 cuotas de $ 8.884,88, la primera vence el 23/11/2026."""
    return await _otorgado(staff, admin, solicitud(escenario, await crear_linea()))


async def test_paga_con_mercado_pago_y_tesoreria_confirma(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = prestamo["id"]
    antes = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert antes["puede_pagar_mp"] is True
    assert antes["cobros_mp"] == []

    referencia, vuelta = await _cobrado(notario, mp, pid)
    cobro = mp.cobros[-1]
    assert cobro["importe"] == D("8884.88")
    assert cobro["titulo"] == f"Préstamo N° {prestamo['numero']} · cuota 1 de 12"
    # Cuota al día: el cobro vence con la cuota.
    assert cobro["vence"].date() == date(2026, 11, 23)
    assert vuelta["estado"] == "approved"
    assert vuelta["boleta_id"] is None
    assert vuelta["cuota"] == {
        "prestamo_id": pid,
        "prestamo_numero": prestamo["numero"],
        "numero": 1,
    }
    # El escribano no ve la comisión de Mercado Pago.
    assert vuelta["comision"] is None

    # Aprobado por Mercado Pago no es pagado: la cuota sigue pendiente hasta que confirma Tesorería.
    a_confirmar = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert a_confirmar["plan"][0]["estado"] == "PENDIENTE"
    assert a_confirmar["puede_pagar_mp"] is False
    [c] = a_confirmar["cobros_mp"]
    assert (c["cuota"], c["estado"], c["a_confirmar"]) == (1, "approved", True)
    assert c["importe_pagado"] == "8884.88"
    assert (await _pagar(notario, pid)).status_code == 409
    # Registrarla a mano la cobraría dos veces.
    a_mano = await tesoreria.post(
        f"/api/v1/prestamos/{pid}/cuotas/1/pago",
        json={"fecha_pago": "2026-10-23", "importe": "8884.88"},
    )
    assert a_mano.status_code == 409
    assert "Mercado Pago" in a_mano.json()["detail"]

    confirmar = f"/api/v1/prestamos/{pid}/mercadopago/{referencia}/confirmar"
    assert (await notario.post(confirmar)).status_code == 403
    confirmado = await tesoreria.post(confirmar)
    assert confirmado.status_code == 200, confirmado.text
    p = confirmado.json()
    assert p["plan"][0]["estado"] == "PAGADA"
    assert p["plan"][0]["fecha_pago"] == "2026-10-23"
    assert p["plan"][0]["importe_pagado"] == "8884.88"
    assert p["cobros_mp"][0]["a_confirmar"] is False
    assert p["cobros_mp"][0]["confirmado_en"] is not None
    assert (await tesoreria.post(confirmar)).status_code == 409

    # La próxima cuota ya se puede pagar.
    assert (await notario.get(f"/api/v1/prestamos/{pid}")).json()["puede_pagar_mp"] is True
    [pagada] = await _eventos(db_session, "PRESTAMO_CUOTA_PAGADA")
    assert pagada.details is not None
    assert pagada.details["origen"] == "MERCADO_PAGO"
    assert pagada.details["pago_mp_id"] == referencia
    [acreditado] = await _eventos(db_session, "PAGO_MP_ACREDITADO")
    assert acreditado.details is not None
    assert acreditado.details["importe_coincide"] is True
    assert acreditado.details["cuota"] == 1

    # Tesorería lo ve en el registro de Mercado Pago, con la cuota que paga.
    registro = (await tesoreria.get("/api/v1/pagos/mercadopago")).json()["items"]
    [fila] = [x for x in registro if x["id"] == referencia]
    assert fila["cuota"]["numero"] == 1
    assert fila["comision"] == "1234.56"


async def test_importe_distinto_no_se_confirma(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = prestamo["id"]
    referencia, _ = await _cobrado(notario, mp, pid, transaction_amount=D("8000.00"))
    r = await tesoreria.post(f"/api/v1/prestamos/{pid}/mercadopago/{referencia}/confirmar")
    assert r.status_code == 409
    assert "$ 8.000,00" in r.json()["detail"]
    detalle = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert detalle["plan"][0]["estado"] == "PENDIENTE"
    [acreditado] = await _eventos(db_session, "PAGO_MP_ACREDITADO")
    assert acreditado.severity == "WARNING"
    assert acreditado.details is not None
    assert acreditado.details["importe_coincide"] is False


async def test_rechazado_no_queda_a_confirmar(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
) -> None:
    pid = prestamo["id"]
    referencia, vuelta = await _cobrado(notario, mp, pid, status="rejected")
    assert vuelta["estado"] == "rejected"
    detalle = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert detalle["cobros_mp"][0]["a_confirmar"] is False
    assert detalle["puede_pagar_mp"] is True
    r = await tesoreria.post(f"/api/v1/prestamos/{pid}/mercadopago/{referencia}/confirmar")
    assert r.status_code == 409


async def test_dos_pagos_de_la_misma_cuota(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    """El escribano abre dos cobros y paga los dos: se confirma uno y el otro queda para
    devolver, a la vista de Tesorería."""
    pid = prestamo["id"]
    assert (await _pagar(notario, pid)).status_code == 201
    assert (await _pagar(notario, pid)).status_code == 201
    primero, segundo = mp.cobros[0]["referencia"], mp.cobros[1]["referencia"]
    for referencia in (primero, segundo):
        mp.informar(referencia, transaction_amount=D("8884.88"))
        await notario.post(f"/api/v1/pagos/mercadopago/{referencia}/sincronizar")
    assert len(await _eventos(db_session, "PAGO_MP_DUPLICADO")) == 1

    url = f"/api/v1/prestamos/{pid}/mercadopago/{{}}/confirmar"
    assert (await tesoreria.post(url.format(primero))).status_code == 200
    sobra = await tesoreria.post(url.format(segundo))
    assert sobra.status_code == 409
    assert "devolverlo" in sobra.json()["detail"]
    pagadas = [c for c in (await notario.get(f"/api/v1/prestamos/{pid}")).json()["plan"]]
    assert [c["estado"] for c in pagadas[:2]] == ["PAGADA", "PENDIENTE"]


async def test_cuota_vencida_se_cobra_hasta_hoy(
    notario: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.pagos import mercadopago_service

    monkeypatch.setattr(mercadopago_service, "today_local", lambda: date(2026, 12, 5))
    assert (await _pagar(notario, prestamo["id"])).status_code == 201
    assert mp.cobros[-1]["vence"].date() == date(2026, 12, 5)
    assert mp.cobros[-1]["importe"] == D("8884.88")


async def test_quien_puede_pagar(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    mp: MercadoPagoFalso,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    prestamo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El personal no inicia el pago: lo paga quien tomó el préstamo.
    assert (await _pagar(staff, prestamo["id"])).status_code == 403
    assert (await staff.get(f"/api/v1/prestamos/{prestamo['id']}")).json()[
        "puede_pagar_mp"
    ] is False
    # Un préstamo ajeno no existe para el escribano.
    ajeno = await _otorgado(
        staff,
        admin,
        solicitud(
            escenario,
            await crear_linea(codigo="OTRA_LINEA"),
            escribano_id=str(escenario.adscripto.id),
        ),
    )
    assert (await _pagar(notario, ajeno["id"])).status_code == 404
    # Sin Mercado Pago configurado, el botón no aparece y el pedido se rechaza.
    monkeypatch.setattr(get_settings(), "MERCADOPAGO_ACCESS_TOKEN", SecretStr(""))
    assert (await _pagar(notario, prestamo["id"])).status_code == 503
    detalle = (await notario.get(f"/api/v1/prestamos/{prestamo['id']}")).json()
    assert detalle["puede_pagar_mp"] is False
    assert mp.cobros == []


async def test_la_base_exige_boleta_o_cuota(
    notario: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    await _cobrado(notario, mp, prestamo["id"])
    for sentencia in (
        "UPDATE pagos_mercadopago SET cuota_id = NULL",
        # Confirmar sin decir quién.
        "UPDATE pagos_mercadopago SET confirmado_en = now()",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(sentencia))


async def test_en_dolares_no(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    mp: MercadoPagoFalso,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    """Mercado Pago cobra en pesos: una cuota en dólares la cobra Tesorería."""
    usd = await _otorgado(
        staff,
        admin,
        solicitud(
            escenario,
            await crear_linea(**LINEA_USD),
            capital="50000",
            cuotas=60,
            ingreso_neto="3301",
        ),
    )
    assert (await _pagar(notario, usd["id"])).status_code == 409
    assert (await notario.get(f"/api/v1/prestamos/{usd['id']}")).json()["puede_pagar_mp"] is False
    assert mp.cobros == []


async def test_devolucion_despues_de_confirmar(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    """Mercado Pago informa una devolución de un cobro ya confirmado: se guarda y se avisa."""
    pid = prestamo["id"]
    referencia, _ = await _cobrado(notario, mp, pid)
    confirmado = await tesoreria.post(f"/api/v1/prestamos/{pid}/mercadopago/{referencia}/confirmar")
    assert confirmado.status_code == 200, confirmado.text
    mp.pagos[referencia][0]["status"] = "refunded"
    vuelta = await notario.post(f"/api/v1/pagos/mercadopago/{referencia}/sincronizar")
    assert vuelta.status_code == 200, vuelta.text
    assert vuelta.json()["estado"] == "refunded"
    [revertido] = await _eventos(db_session, "PAGO_MP_REVERTIDO")
    assert revertido.severity == "CRITICAL"
    detalle = (await tesoreria.get(f"/api/v1/prestamos/{pid}")).json()
    assert detalle["cobros_mp"][0]["estado"] == "refunded"
    assert detalle["cobros_mp"][0]["confirmado_en"] is not None


async def test_el_garante_no_ve_los_pagos_del_titular(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    mp: MercadoPagoFalso,
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    # Préstamo del adscripto con el titular (usuario `notario`) como garante.
    p = await _otorgado(
        staff,
        admin,
        solicitud(
            escenario,
            await crear_linea(requiere_garante=True),
            escribano_id=str(escenario.adscripto.id),
            garante_escribano_id=str(escenario.titular.id),
        ),
    )
    cuota_id = await db_session.scalar(
        select(CuotaPrestamo.id).where(
            CuotaPrestamo.prestamo_id == uuid.UUID(p["id"]), CuotaPrestamo.numero == 1
        )
    )
    db_session.add(
        PagoMercadoPago(
            cuota_id=cuota_id,
            preference_id="pref-garante",
            importe_boleta=D("8884.88"),
            iniciado_por_user_id=escenario.titular_user.id,
            estado="approved",
            mp_payment_id="555",
            medio_pago="visa",
            importe_pagado=D("8884.88"),
            moneda="ARS",
        )
    )
    await db_session.flush()

    visto = (await notario.get(f"/api/v1/prestamos/{p['id']}")).json()
    assert visto["cobros_mp"] == []
    assert visto["puede_pagar_mp"] is False
    # El garante no paga la cuota del titular con Mercado Pago.
    assert (await _pagar(notario, p["id"])).status_code == 403
    completo = (await staff.get(f"/api/v1/prestamos/{p['id']}")).json()
    assert completo["cobros_mp"][0]["medio_pago"] == "visa"
