"""Préstamos de punta a punta: simular, solicitar, otorgar (cuatro ojos), cobrar y cancelar."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from tests.ddjj.conftest import Escenario
from tests.pagos.conftest import boleta  # noqa: F401 - fixture compartida

D = Decimal


def solicitud(e: Escenario, linea: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "escribano_id": str(e.titular.id),
        "linea_id": linea["id"],
        "capital": "100000.00",
        "cuotas": 12,
        "ingreso_neto": "60000.00",
        **extra,
    }


async def _otorgado(
    staff: AsyncClient, admin: AsyncClient, cuerpo: dict[str, Any]
) -> dict[str, Any]:
    creado = await staff.post("/api/v1/prestamos", json=cuerpo)
    assert creado.status_code == 201, creado.text
    otorgado = await admin.post(f"/api/v1/prestamos/{creado.json()['id']}/otorgar")
    assert otorgado.status_code == 200, otorgado.text
    body: dict[str, Any] = otorgado.json()
    return body


async def test_simular_otorgar_y_cobrar_hasta_cancelar(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    tesoreria: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    linea = await crear_linea()

    sim = await notario.post(
        "/api/v1/prestamos/simular",
        json={"linea_id": linea["id"], "capital": "100000", "cuotas": 12, "ingreso_neto": "60000"},
    )
    assert sim.status_code == 200, sim.text
    s = sim.json()
    assert s["cuota_maxima"] == "8884.88"
    assert s["afectacion"] == "14.8082"
    assert s["impedimentos"] == []
    assert s["tasa_es_ejemplo"] is True
    assert s["totales"] == {"capital": "100000.00", "intereses": "6618.53", "total": "106618.53"}

    creado = await staff.post("/api/v1/prestamos", json=solicitud(escenario, linea))
    assert creado.status_code == 201, creado.text
    pid = creado.json()["id"]
    assert creado.json()["estado"] == "SOLICITADO"
    # Cuatro ojos: quien cargó no resuelve (y la Caja no tiene prestamos:approve).
    assert (await staff.post(f"/api/v1/prestamos/{pid}/otorgar")).status_code == 403

    otorgado = (await admin.post(f"/api/v1/prestamos/{pid}/otorgar")).json()
    assert otorgado["estado"] == "OTORGADO"
    assert otorgado["fecha_otorgamiento"] == "2026-10-23"
    assert otorgado["plan"][0]["vencimiento"] == "2026-11-23"
    assert sum(D(c["amortizacion"]) for c in otorgado["plan"]) == D("100000.00")
    assert otorgado["plan"][-1]["saldo_final"] == "0.00"
    assert otorgado["saldo_capital"] == "100000.00"

    # El escribano ve su préstamo; Tesorería cobra en orden.
    assert (await notario.get(f"/api/v1/prestamos/{pid}")).status_code == 200
    url = f"/api/v1/prestamos/{pid}/cuotas"
    fuera_de_orden = await tesoreria.post(
        f"{url}/2/pago", json={"fecha_pago": "2026-10-23", "importe": "8884.88"}
    )
    importe_mal = await tesoreria.post(
        f"{url}/1/pago", json={"fecha_pago": "2026-10-23", "importe": "8000.00"}
    )
    assert fuera_de_orden.status_code == 409
    assert importe_mal.status_code == 422

    reloj(date(2027, 12, 1))
    for cuota in otorgado["plan"]:
        r = await tesoreria.post(
            f"{url}/{cuota['numero']}/pago",
            json={"fecha_pago": cuota["vencimiento"], "importe": cuota["cuota"]},
        )
        assert r.status_code == 200, r.text
    final = r.json()
    assert final["estado"] == "CANCELADO"
    assert final["saldo_capital"] == "0.00"
    assert final["cuotas_pagadas"] == 12
    otra = await tesoreria.post(f"{url}/1/pago", json={"fecha_pago": "2027-01-01", "importe": "1"})
    assert otra.status_code == 409
    eventos = set((await db_session.scalars(select(AuditSecurityLog.event_type))).all())
    assert {
        "PRESTAMO_SOLICITADO",
        "PRESTAMO_OTORGADO",
        "PRESTAMO_CUOTA_PAGADA",
        "PRESTAMO_CANCELADO",
    } <= eventos


async def test_tope_de_afectacion_con_otros_prestamos(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    linea = await crear_linea()
    # 8.884,88 / 30.000 = 29,6163 %: entra justo.
    await _otorgado(staff, admin, solicitud(escenario, linea, ingreso_neto="30000"))

    # Un segundo préstamo igual entraría solo (29,6163 %), pero sumado al primero no.
    segundo = await staff.post(
        "/api/v1/prestamos", json=solicitud(escenario, linea, ingreso_neto="30000")
    )
    excede = await staff.post(
        "/api/v1/prestamos", json=solicitud(escenario, linea, ingreso_neto="29000")
    )

    assert segundo.status_code == 422
    assert "el 59,2326 % del ingreso neto" in segundo.json()["detail"]
    assert "tope de la línea es 30 %" in segundo.json()["detail"]
    assert segundo.json()["impedimentos"]
    assert excede.status_code == 422


async def test_reglas_del_garante(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    boleta: dict[str, Any],  # noqa: F811 - boleta pendiente del registro del titular
) -> None:
    linea = await crear_linea(requiere_garante=True)
    titular, adscripto = str(escenario.titular.id), str(escenario.adscripto.id)
    base = solicitud(escenario, linea, escribano_id=adscripto)

    sin_garante = await staff.post("/api/v1/prestamos", json=base)
    propio = await staff.post("/api/v1/prestamos", json={**base, "garante_escribano_id": adscripto})
    habil = await staff.post("/api/v1/prestamos", json={**base, "garante_escribano_id": titular})
    assert sin_garante.status_code == 422
    assert "garante" in sin_garante.json()["detail"]
    assert propio.status_code == 422
    assert habil.status_code == 201, habil.text

    # Vencida la boleta del registro del titular, tiene deuda de aportes: ya no puede garantizar.
    reloj(date(2026, 11, 5))
    con_deuda = await staff.post(
        "/api/v1/prestamos", json={**base, "garante_escribano_id": titular}
    )
    assert con_deuda.status_code == 422
    assert "deuda de aportes" in con_deuda.json()["detail"]
    # Y al otorgar se reevalúa: la solicitud que era viable ya no se otorga.
    otorgar = await admin.post(f"/api/v1/prestamos/{habil.json()['id']}/otorgar")
    assert otorgar.status_code == 409
    detalle = (await admin.get(f"/api/v1/prestamos/{habil.json()['id']}")).json()
    assert any("deuda de aportes" in i for i in detalle["impedimentos_actuales"])


async def test_mora_propia_y_como_garante(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    sin_garante = await crear_linea()
    con_garante = await crear_linea(codigo="LINEA_GARANTIA", requiere_garante=True)
    titular, adscripto = str(escenario.titular.id), str(escenario.adscripto.id)
    # El titular toma un préstamo con el adscripto como garante.
    await _otorgado(
        staff,
        admin,
        solicitud(escenario, con_garante, garante_escribano_id=adscripto),
    )

    # Pasa el primer vencimiento sin pago: el titular está en mora y el adscripto garantiza mora.
    reloj(date(2026, 12, 1))
    titular_pide = await staff.post("/api/v1/prestamos", json=solicitud(escenario, sin_garante))
    adscripto_garantiza = await staff.post(
        "/api/v1/prestamos",
        json=solicitud(
            escenario, con_garante, escribano_id=titular, garante_escribano_id=adscripto
        ),
    )
    listado = (await staff.get("/api/v1/prestamos", params={"estado": "OTORGADO"})).json()

    assert titular_pide.status_code == 422
    assert "vencidas impagas" in titular_pide.json()["detail"]
    assert adscripto_garantiza.status_code == 422
    assert "ya garantiza" in adscripto_garantiza.json()["detail"]
    assert listado[0]["cuotas_vencidas"] == 1


async def test_rechazo_y_snap_de_condiciones(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    linea = await crear_linea()
    otorgado = await _otorgado(staff, admin, solicitud(escenario, linea))
    pedido = (await staff.post("/api/v1/prestamos", json=solicitud(escenario, linea))).json()

    # Cambia la tasa de la línea: lo otorgado no cambia; lo solicitado conserva lo pactado.
    actualizada = await staff.put(
        f"/api/v1/prestamos/lineas/{linea['id']}", json={**linea, "tna": "48.0000"}
    )
    assert actualizada.status_code == 200
    despues = (await admin.get(f"/api/v1/prestamos/{otorgado['id']}")).json()
    assert despues["tna"] == "12.0000"
    assert despues["plan"] == otorgado["plan"]
    assert (await admin.get(f"/api/v1/prestamos/{pedido['id']}")).json()["tna"] == "12.0000"

    corto = await admin.post(f"/api/v1/prestamos/{pedido['id']}/rechazar", json={"motivo": "no"})
    rechazado = await admin.post(
        f"/api/v1/prestamos/{pedido['id']}/rechazar",
        json={"motivo": "Documentación de ingresos incompleta."},
    )
    assert corto.status_code == 422
    assert rechazado.json()["estado"] == "RECHAZADO"
    assert (await admin.post(f"/api/v1/prestamos/{pedido['id']}/otorgar")).status_code == 409


async def test_permisos(
    notario: AsyncClient,
    client: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    linea = await crear_linea()
    otorgado = await _otorgado(
        staff, admin, solicitud(escenario, linea, escribano_id=str(escenario.adscripto.id))
    )
    otro = await make_user(db_session)
    await login(client, otro)

    assert (
        await notario.post("/api/v1/prestamos", json=solicitud(escenario, linea))
    ).status_code == 403
    assert (await notario.post("/api/v1/prestamos/lineas", json=linea)).status_code == 403
    # El préstamo es del adscripto: el titular (sin cargo de garante) no lo ve.
    assert (await notario.get(f"/api/v1/prestamos/{otorgado['id']}")).status_code == 404
    assert (await client.get("/api/v1/prestamos")).json() == []
    visto_por_escribano = await notario.get("/api/v1/prestamos")
    assert visto_por_escribano.status_code == 200


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE prestamos_cuotas SET cuota = cuota + 1, interes = interes + 1",
        "UPDATE prestamos SET capital = 1 WHERE estado = 'OTORGADO'",
        "UPDATE prestamos SET estado = 'SOLICITADO'",
        "DELETE FROM prestamos_cuotas",
        "DELETE FROM prestamos",
        "TRUNCATE prestamos_lineas CASCADE",
        "INSERT INTO prestamos_cuotas (prestamo_id, numero, vencimiento, saldo_inicial, "
        "amortizacion, interes, cuota, saldo_final) SELECT id, 99, current_date, 1, 1, 0, 1, 0 "
        "FROM prestamos",
    ],
)
async def test_inmutable_en_la_base(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    db_session: AsyncSession,
    statement: str,
) -> None:
    await _otorgado(staff, admin, solicitud(escenario, await crear_linea()))
    rechazo = r"permission denied|no permitido|no se modifica|no cambia|solo cambia"

    with pytest.raises(DBAPIError, match=rechazo):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_escribano_no_sondea_garantes_ajenos(
    notario: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    boleta: dict[str, Any],  # noqa: F811 - el registro del titular tiene una boleta pendiente
) -> None:
    linea = await crear_linea(requiere_garante=True)
    reloj(date(2026, 11, 5))  # la boleta ya venció: el adscripto, del mismo registro, debe aportes

    sim = await notario.post(
        "/api/v1/prestamos/simular",
        json={
            "linea_id": linea["id"],
            "capital": "100000",
            "cuotas": 12,
            "ingreso_neto": "60000",
            "garante_escribano_id": str(escenario.adscripto.id),
        },
    )

    assert sim.status_code == 200
    # Se ignora el garante propuesto: no se revela su situación (deuda, mora).
    assert all("deuda" not in i and "mora" not in i for i in sim.json()["impedimentos"])
    assert any("exige un garante" in i for i in sim.json()["impedimentos"])


async def test_no_resuelve_quien_es_titular_o_garante(
    staff: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    app: Any,
    db_session: AsyncSession,
) -> None:
    import pyotp

    from tests.ddjj.conftest import _client
    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    # Un usuario con permiso para otorgar que además es el escribano adscripto.
    secret = pyotp.random_base32()
    usuario = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    escenario.adscripto.user_id = usuario.id
    await db_session.commit()
    linea = await crear_linea()
    propio = await staff.post(
        "/api/v1/prestamos",
        json=solicitud(escenario, linea, escribano_id=str(escenario.adscripto.id)),
    )
    async with await _client(app) as cliente:
        await login(cliente, usuario, secret)
        detalle = await cliente.get(f"/api/v1/prestamos/{propio.json()['id']}")
        otorgar = await cliente.post(f"/api/v1/prestamos/{propio.json()['id']}/otorgar")

    assert detalle.json()["puede_resolver"] is False
    assert otorgar.status_code == 403
    assert "titular o garante" in otorgar.json()["detail"]
