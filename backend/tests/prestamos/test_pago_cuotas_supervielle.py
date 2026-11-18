"""Pago de cuotas de préstamo en pesos con el botón Supervielle (decisión de la Caja del
17/11/2026): el escribano paga la próxima cuota por su importe exacto (la comisión la absorbe la
Caja), el banco informa el pago y la cuota recién pasa a pagada cuando Tesorería confirma el cobro
(regla PAGO). El banco se simula con el `BancoFalso` de los tests de boletas."""

# ruff: noqa: F811

import uuid
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.pagos import supervielle_service
from app.modules.pagos.models import PagoSupervielle
from tests.ddjj.conftest import HOY, Escenario, _client, _escribano
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.pagos.test_mercadopago import MercadoPagoFalso, mp  # noqa: F401 - fixture
from tests.pagos.test_supervielle import BancoFalso, _comisiones_aprobadas, banco  # noqa: F401
from tests.prestamos.test_monedas import LINEA_USD
from tests.prestamos.test_prestamos import _otorgado, solicitud

D = Decimal
CUOTA = D("8884.88")


@pytest.fixture
def hoy_banco(banco: BancoFalso, monkeypatch: pytest.MonkeyPatch) -> BancoFalso:
    """El botón con el mismo «hoy» que los préstamos (el préstamo se otorga ese día)."""
    monkeypatch.setattr(supervielle_service, "today_local", lambda: HOY)
    return banco


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


async def _pagar(cliente: AsyncClient, prestamo_id: str) -> Any:
    return await cliente.post(f"/api/v1/prestamos/{prestamo_id}/supervielle")


async def _item(session: AsyncSession, pago_id: str) -> PagoSupervielle:
    item = await session.get(PagoSupervielle, uuid.UUID(pago_id))
    assert item is not None
    await session.refresh(item)
    return item


async def _pagado(
    notario: AsyncClient,
    banco: BancoFalso,
    session: AsyncSession,
    prestamo_id: str,
    **pago: Any,
) -> tuple[str, dict[str, Any]]:
    """Publica la próxima cuota, el banco informa el pago y el escribano toca «Ya pagué»."""
    r = await _pagar(notario, prestamo_id)
    assert r.status_code == 201, r.text
    pago_id: str = r.json()["pago_id"]
    item = await _item(session, pago_id)
    banco.informar(
        item.hash, **{"importe": item.importe_boleta, "fecha": "2026-10-23T10:15:00.000", **pago}
    )
    vuelta = await notario.post(f"/api/v1/pagos/supervielle/{pago_id}/sincronizar")
    assert vuelta.status_code == 200, vuelta.text
    body: dict[str, Any] = vuelta.json()
    return pago_id, body


async def _eventos(session: AsyncSession, tipo: str) -> list[AuditSecurityLog]:
    filas = await session.scalars(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == tipo)
    )
    return list(filas.all())


def _confirmar(prestamo_id: str, pago_id: str) -> str:
    return f"/api/v1/prestamos/{prestamo_id}/supervielle/{pago_id}/confirmar"


async def test_publica_la_cuota_y_tesoreria_confirma(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = prestamo["id"]
    antes = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert antes["puede_pagar_spv"] is True
    assert antes["cobros_spv"] == []

    r = await _pagar(notario, pid)
    assert r.status_code == 201, r.text
    pago_id = r.json()["pago_id"]
    item = await _item(db_session, pago_id)
    assert r.json()["url_pago"] == item.link_pago
    # Se publica el importe exacto de la cuota (la comisión la absorbe la Caja), con su
    # vencimiento.
    (publicada,) = hoy_banco.publicaciones
    assert publicada["importe"] == CUOTA
    assert publicada["vence"] == date(2026, 11, 23)
    assert publicada["descripcion"] == (
        f"Caja Notarial · Préstamo N° {prestamo['numero']} · Cuota 1 de 12"
    )
    assert publicada["identificadores"][0] == pago_id
    assert (item.boleta_id, item.importe_boleta) == (None, CUOTA)
    # Mientras la deuda siga vigente se reutiliza su link (el banco no la anula).
    otra = await _pagar(notario, pid)
    assert otra.json()["pago_id"] == pago_id
    assert len(hoy_banco.publicaciones) == 1
    publicada_detalle = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    [creado] = publicada_detalle["cobros_spv"]
    assert (creado["cuota"], creado["estado"], creado["a_confirmar"]) == (1, "CREADO", False)

    # El banco aprueba el pago; el escribano verifica.
    hoy_banco.informar(item.hash, importe=CUOTA, fecha="2026-10-23T10:15:00.000")
    vuelta = await notario.post(f"/api/v1/pagos/supervielle/{pago_id}/sincronizar")
    assert vuelta.status_code == 200, vuelta.text
    body = vuelta.json()
    assert body["estado"] == "APROBADO"
    assert body["boleta_id"] is None
    assert body["cuota"] == {
        "prestamo_id": pid,
        "prestamo_numero": prestamo["numero"],
        "numero": 1,
    }
    # El escribano no ve la comisión.
    assert body["comision_estimada"] is None

    # Aprobado por el banco no es pagado: queda a confirmar por Tesorería (sin comprobante en la
    # mesa de boletas).
    a_confirmar = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert a_confirmar["plan"][0]["estado"] == "PENDIENTE"
    assert a_confirmar["puede_pagar_spv"] is False
    assert a_confirmar["puede_pagar_mp"] is False
    [c] = a_confirmar["cobros_spv"]
    assert (c["cuota"], c["estado"], c["a_confirmar"]) == (1, "APROBADO", True)
    assert c["importe_pagado"] == "8884.88"
    assert (await _item(db_session, pago_id)).comprobante_id is None
    [acreditado] = await _eventos(db_session, "PAGO_SPV_ACREDITADO")
    assert acreditado.details is not None
    assert acreditado.details["importe_coincide"] is True
    assert acreditado.details["cuota"] == 1
    assert acreditado.new_value == {"estado": "APROBADO", "a_confirmar_por": "TESORERIA"}
    # Tesorería lo ve en el registro de pagos Supervielle, con la cuota que paga.
    registro = (await tesoreria.get("/api/v1/pagos/supervielle")).json()["items"]
    [fila] = [x for x in registro if x["id"] == pago_id]
    assert fila["cuota"]["numero"] == 1
    assert fila["confirmado_en"] is None
    # Registrarla a mano la cobraría dos veces.
    a_mano = await tesoreria.post(
        f"/api/v1/prestamos/{pid}/cuotas/1/pago",
        json={"fecha_pago": "2026-10-23", "importe": "8884.88"},
    )
    assert a_mano.status_code == 409
    assert "Supervielle" in a_mano.json()["detail"]

    confirmado = await tesoreria.post(_confirmar(pid, pago_id))
    assert confirmado.status_code == 200, confirmado.text
    p = confirmado.json()
    assert p["plan"][0]["estado"] == "PAGADA"
    assert p["plan"][0]["fecha_pago"] == "2026-10-23"
    assert p["plan"][0]["importe_pagado"] == "8884.88"
    assert p["cobros_spv"][0]["a_confirmar"] is False
    assert p["cobros_spv"][0]["confirmado_en"] is not None
    [pagada] = await _eventos(db_session, "PRESTAMO_CUOTA_PAGADA")
    assert pagada.details is not None
    assert pagada.details["origen"] == "SUPERVIELLE"
    assert pagada.details["pago_spv_id"] == pago_id
    # La próxima cuota ya se puede pagar.
    assert (await notario.get(f"/api/v1/prestamos/{pid}")).json()["puede_pagar_spv"] is True


async def test_la_comision_la_absorbe_la_caja_y_se_guarda_con_sus_vigencias(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    await _comisiones_aprobadas(db_session)
    pago_id, body = await _pagado(notario, hoy_banco, db_session, prestamo["id"], id_medio_pago=2)
    assert body["comision_estimada"] is None
    item = await _item(db_session, pago_id)
    centavo = D("0.01")
    sin_iva = (CUOTA * D("0.004")).quantize(centavo, ROUND_HALF_UP) + (CUOTA * D("0.02")).quantize(
        centavo, ROUND_HALF_UP
    )
    esperada = sin_iva + (sin_iva * D("0.21")).quantize(centavo, ROUND_HALF_UP)
    # Al escribano se le cobró la cuota exacta; la comisión queda como dato de la Caja.
    assert hoy_banco.publicaciones[0]["importe"] == CUOTA
    assert item.comision_estimada == esperada
    # Regla SNAP: quedan las vigencias con que se estimó.
    assert item.vigencia_comision_boton_id is not None
    assert item.vigencia_comision_medio_id is not None
    assert item.vigencia_comision_iva_id is not None
    [visto] = (await tesoreria.get("/api/v1/pagos/supervielle")).json()["items"]
    assert visto["comision_estimada"] == f"{esperada:.2f}"
    assert visto["importe_neto_estimado"] == f"{CUOTA - esperada:.2f}"


async def test_cuota_en_dolares_se_rechaza(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    hoy_banco: BancoFalso,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    """El botón cobra en pesos: una cuota en dólares no se publica."""
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
    r = await _pagar(notario, usd["id"])
    assert r.status_code == 409
    assert "cobra en pesos" in r.json()["detail"]
    assert "dólares" in r.json()["detail"]
    assert (await notario.get(f"/api/v1/prestamos/{usd['id']}")).json()["puede_pagar_spv"] is False
    assert hoy_banco.publicaciones == []


async def test_cuota_ya_pagada_se_rechaza(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    mp: MercadoPagoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = prestamo["id"]
    pago_id, _ = await _pagado(notario, hoy_banco, db_session, pid)
    # Pagada y esperando a Tesorería: no se publica otra vez, ni por Supervielle ni por
    # Mercado Pago.
    otra = await _pagar(notario, pid)
    assert otra.status_code == 409
    assert "ya está pagada" in otra.json()["detail"]
    assert len(hoy_banco.publicaciones) == 1
    con_mp = await notario.post(f"/api/v1/prestamos/{pid}/mercadopago")
    assert con_mp.status_code == 409
    assert "Supervielle" in con_mp.json()["detail"]
    assert mp.cobros == []

    assert (await tesoreria.post(_confirmar(pid, pago_id))).status_code == 200
    # Ya confirmada, no se confirma de nuevo.
    segunda = await tesoreria.post(_confirmar(pid, pago_id))
    assert segunda.status_code == 409
    assert "ya está confirmado" in segunda.json()["detail"]


async def test_dos_pagos_de_la_misma_cuota(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    """La cuota se pagó por Tesorería y además con Supervielle: el pago sobra y Tesorería lo
    ve; no se puede aplicar a la cuota ya pagada."""
    pid = prestamo["id"]
    r = await _pagar(notario, pid)
    pago_id = r.json()["pago_id"]
    a_mano = await tesoreria.post(
        f"/api/v1/prestamos/{pid}/cuotas/1/pago",
        json={"fecha_pago": "2026-10-23", "importe": "8884.88"},
    )
    assert a_mano.status_code == 200, a_mano.text
    item = await _item(db_session, pago_id)
    hoy_banco.informar(item.hash, importe=CUOTA, fecha="2026-10-23T10:15:00.000")
    await notario.post(f"/api/v1/pagos/supervielle/{pago_id}/sincronizar")
    sobra = await tesoreria.post(_confirmar(pid, pago_id))
    assert sobra.status_code == 409
    assert "devolverlo" in sobra.json()["detail"]


async def test_importe_distinto_no_se_confirma(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = prestamo["id"]
    pago_id, _ = await _pagado(notario, hoy_banco, db_session, pid, importe=D("8000.00"))
    r = await tesoreria.post(_confirmar(pid, pago_id))
    assert r.status_code == 409
    assert "$ 8.000,00" in r.json()["detail"]
    [acreditado] = await _eventos(db_session, "PAGO_SPV_ACREDITADO")
    assert acreditado.severity == "WARNING"


async def test_antes_de_confirmar_se_consulta_al_banco(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    """Una reversión cuyo aviso todavía no llegó bloquea la confirmación; con el banco caído no
    se confirma."""
    pid = prestamo["id"]
    pago_id, _ = await _pagado(notario, hoy_banco, db_session, pid)
    hoy_banco.caido = True
    assert (await tesoreria.post(_confirmar(pid, pago_id))).status_code == 503
    hoy_banco.caido = False
    item = await _item(db_session, pago_id)
    hoy_banco.pagos[item.hash][0].update(id_estado_pago=4, estado_pago="Reversado")
    r = await tesoreria.post(_confirmar(pid, pago_id))
    assert r.status_code == 409
    assert (await _item(db_session, pago_id)).estado == "REVERSADO"
    detalle = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert detalle["plan"][0]["estado"] == "PENDIENTE"
    assert len(await _eventos(db_session, "PAGO_SPV_REVERTIDO")) == 1


async def test_permisos(
    app: FastAPI,
    notario: AsyncClient,
    staff: AsyncClient,
    tesoreria: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    pid = prestamo["id"]
    # El personal no inicia el pago: lo paga quien tomó el préstamo.
    assert (await _pagar(staff, pid)).status_code == 403
    assert (await staff.get(f"/api/v1/prestamos/{pid}")).json()["puede_pagar_spv"] is False
    pago_id, _ = await _pagado(notario, hoy_banco, db_session, pid)
    # El escribano no confirma su propio pago: es tarea de Tesorería.
    assert (await notario.post(_confirmar(pid, pago_id))).status_code == 403
    # Un escribano ajeno no ve el préstamo ni consulta el pago.
    ajeno = await make_user(db_session)
    await _escribano(db_session, "Ajeno", ajeno)
    await db_session.commit()
    async with await _client(app) as otro:
        await login(otro, ajeno)
        assert (await _pagar(otro, pid)).status_code == 404
        sincronizar = await otro.post(f"/api/v1/pagos/supervielle/{pago_id}/sincronizar")
        assert sincronizar.status_code == 404
    # Un pago de otro préstamo no se confirma desde este.
    assert (await tesoreria.post(_confirmar(pid, str(uuid.uuid4())))).status_code == 404
    detalle = (await notario.get(f"/api/v1/prestamos/{pid}")).json()
    assert detalle["plan"][0]["estado"] == "PENDIENTE"


async def test_sin_configurar_no_se_ofrece(notario: AsyncClient, prestamo: dict[str, Any]) -> None:
    r = await _pagar(notario, prestamo["id"])
    assert r.status_code == 503
    assert "Tesorería" in r.json()["detail"]
    detalle = (await notario.get(f"/api/v1/prestamos/{prestamo['id']}")).json()
    assert detalle["puede_pagar_spv"] is False


async def test_cuota_vencida_se_publica_hasta_manana(
    notario: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El banco exige un vencimiento posterior al día de la publicación."""
    monkeypatch.setattr(supervielle_service, "today_local", lambda: date(2026, 12, 5))
    assert (await _pagar(notario, prestamo["id"])).status_code == 201
    assert hoy_banco.publicaciones[-1]["vence"] == date(2026, 12, 6)
    assert hoy_banco.publicaciones[-1]["importe"] == CUOTA


async def test_la_base_exige_boleta_o_cuota(
    notario: AsyncClient,
    hoy_banco: BancoFalso,
    prestamo: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    await _pagado(notario, hoy_banco, db_session, prestamo["id"])
    for sentencia in (
        "UPDATE pagos_supervielle SET cuota_id = NULL",
        # Confirmar sin decir quién.
        "UPDATE pagos_supervielle SET confirmado_en = now()",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(sentencia))


async def test_el_garante_no_consulta_el_pago_del_titular(
    app: FastAPI,
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    hoy_banco: BancoFalso,
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    """Préstamo del adscripto con el titular (usuario `notario`) como garante: el garante ve el
    préstamo pero no consulta ni ve el pago con Supervielle del titular."""
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
        text("SELECT id FROM prestamos_cuotas WHERE prestamo_id = :p AND numero = 1"),
        {"p": uuid.UUID(p["id"])},
    )
    item = PagoSupervielle(
        cuota_id=cuota_id,
        id_publicacion=987654,
        hash=str(uuid.uuid4()),
        link_pago="https://recaudaciones.test/publicacion/x",
        importe_boleta=CUOTA,
        vence=date(2026, 11, 23),
        iniciado_por_user_id=escenario.titular_user.id,
        estado="CREADO",
    )
    db_session.add(item)
    await db_session.flush()
    r = await notario.post(f"/api/v1/pagos/supervielle/{item.id}/sincronizar")
    assert r.status_code == 404
    assert (await _pagar(notario, p["id"])).status_code == 403
    visto = (await notario.get(f"/api/v1/prestamos/{p['id']}")).json()
    assert visto["cobros_spv"] == []
    assert visto["puede_pagar_spv"] is False
    # El personal sí lo ve.
    completo = (await staff.get(f"/api/v1/prestamos/{p['id']}")).json()
    assert [c["id"] for c in completo["cobros_spv"]] == [str(item.id)]
