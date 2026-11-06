"""Préstamos en dólares y requisitos de la línea (antigüedad en la matrícula)."""

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.money import format_importe, format_pesos
from app.modules.padron.models import Escribano
from app.modules.prestamos import service
from app.modules.prestamos.catalog import AVISO_TIPO_CAMBIO
from app.modules.prestamos.models import Linea, Prestamo
from tests.ddjj.conftest import HOY, Escenario
from tests.prestamos.test_prestamos import _otorgado, solicitud

D = Decimal
LINEA_USD = {
    "codigo": "HIPOTECARIO_USD_PRUEBA",
    "nombre": "Hipotecario en dólares (prueba)",
    "moneda": "USD",
    "tna": "7.0000",
    "plazo_minimo": 1,
    "plazo_maximo": 60,
    "monto_minimo": "0.01",
    "monto_maximo": "50000.00",
    "garantia": "Hipoteca.",
    "relacion_capital_hipoteca": "70",
    "requiere_certificado_ingresos": True,
    "requiere_certificado_bienes": True,
    "antiguedad_minima_meses": 12,
    "requisito_conducta": "Conducta regular en el último año.",
    "es_ejemplo": False,
}


def test_formato_de_importes() -> None:
    assert format_pesos(D("1081699.06")) == "$ 1.081.699,06"
    assert format_importe(D("50000"), "US$") == "US$ 50.000,00"
    assert format_importe(D("-3.5"), "US$") == "-US$ 3,50"
    assert service.con_moneda(D("990.06"), "USD") == "US$ 990,06"
    assert service.texto_meses(12) == "1 año"
    assert service.texto_meses(24) == "2 años"
    assert service.texto_meses(1) == "1 mes"
    assert service.texto_meses(18) == "18 meses"


async def test_linea_en_dolares_simula_y_otorga_en_dolares(
    notario: AsyncClient,
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    linea = await crear_linea(**LINEA_USD)
    assert linea["moneda"] == "USD"
    assert linea["relacion_capital_hipoteca"] == "70.0000"
    assert linea["antiguedad_minima_meses"] == 12
    assert linea["garantia"] == "Hipoteca."

    sim = await notario.post(
        "/api/v1/prestamos/simular",
        json={"linea_id": linea["id"], "capital": "50000", "cuotas": 60, "ingreso_neto": "3301"},
    )
    assert sim.status_code == 200, sim.text
    s = sim.json()
    assert (s["moneda"], s["cuota_maxima"]) == ("USD", "990.06")
    assert s["impedimentos"] == []
    assert AVISO_TIPO_CAMBIO in s["avisos"]

    fuera = await notario.post(
        "/api/v1/prestamos/simular",
        json={"linea_id": linea["id"], "capital": "60000", "cuotas": 60},
    )
    assert "entre US$ 0,01 y US$ 50.000,00" in fuera.json()["impedimentos"][0]

    p = await _otorgado(
        staff,
        admin,
        solicitud(escenario, linea, capital="50000", cuotas=60, ingreso_neto="3301"),
    )
    assert p["moneda"] == "USD"
    assert p["plan"][0]["cuota"] == "990.06"
    assert p["avisos_actuales"] == []  # ya resuelto: la evaluación quedó congelada
    listado = (await staff.get("/api/v1/prestamos")).json()
    assert {x["moneda"] for x in listado if x["id"] == p["id"]} == {"USD"}


async def test_prestamo_vigente_en_otra_moneda_impide_solicitar(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    """Sin tipo de cambio no se puede sumar pesos y dólares: mezclar monedas evadiría el tope."""
    pesos = await crear_linea()
    dolares = await crear_linea(**LINEA_USD)
    await _otorgado(staff, admin, solicitud(escenario, pesos, ingreso_neto="30000"))

    sim = await staff.post(
        "/api/v1/prestamos/simular",
        json={
            "linea_id": dolares["id"],
            "capital": "50000",
            "cuotas": 60,
            "ingreso_neto": "3301",
            "escribano_id": str(escenario.titular.id),
        },
    )
    assert sim.json()["otras_cuotas"] == "0.00"
    assert service.OTRA_MONEDA in sim.json()["impedimentos"]

    rechazada = await staff.post(
        "/api/v1/prestamos",
        json=solicitud(escenario, dolares, capital="50000", cuotas=60, ingreso_neto="3301"),
    )
    assert rechazada.status_code == 422
    assert service.OTRA_MONEDA in rechazada.json()["impedimentos"]

    # En la misma moneda sigue valiendo el tope habitual (suma las cuotas en pesos).
    misma = await staff.post(
        "/api/v1/prestamos", json=solicitud(escenario, pesos, ingreso_neto="60000")
    )
    assert misma.status_code == 201, misma.text


async def test_solicitud_en_otra_moneda_impide_otorgar(
    staff: AsyncClient,
    admin: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    pesos = await crear_linea()
    dolares = await crear_linea(**LINEA_USD)
    creado = await staff.post("/api/v1/prestamos", json=solicitud(escenario, pesos))
    assert creado.status_code == 201, creado.text
    # Mientras tanto aparece otra solicitud en dólares (p. ej. cargada antes por otra vía).
    db_session.add(
        Prestamo(
            escribano_id=escenario.titular.id,
            linea_id=uuid.UUID(dolares["id"]),
            estado="SOLICITADO",
            moneda="USD",
            sistema="FRANCES",
            tna=D("7.0000"),
            capital=D("50000.00"),
            cuotas=60,
            tasa_es_ejemplo=False,
            ingreso_neto=D("3301.00"),
            otras_cuotas=D("0.00"),
            cuota_maxima=D("990.06"),
            afectacion=D("29.9927"),
            afectacion_maxima=D("30.0000"),
            creado_por_user_id=escenario.titular_user.id,
        )
    )
    await db_session.commit()

    detalle = (await admin.get(f"/api/v1/prestamos/{creado.json()['id']}")).json()
    assert service.OTRA_MONEDA in detalle["impedimentos_actuales"]
    otorgar = await admin.post(f"/api/v1/prestamos/{creado.json()['id']}/otorgar")
    assert otorgar.status_code == 409
    assert service.OTRA_MONEDA in otorgar.json()["impedimentos"]


async def test_solicitud_en_dolares_avisa_el_tipo_de_cambio(
    staff: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
) -> None:
    dolares = await crear_linea(**LINEA_USD)
    creado = await staff.post(
        "/api/v1/prestamos",
        json=solicitud(escenario, dolares, capital="50000", cuotas=60, ingreso_neto="3301"),
    )
    assert creado.status_code == 201, creado.text
    assert creado.json()["moneda"] == "USD"
    assert AVISO_TIPO_CAMBIO in creado.json()["avisos_actuales"]


async def test_la_moneda_de_un_prestamo_no_cambia(
    staff: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    linea = await crear_linea()
    creado = await staff.post("/api/v1/prestamos", json=solicitud(escenario, linea))
    assert creado.status_code == 201, creado.text

    with pytest.raises(DBAPIError, match="la moneda de un préstamo no cambia"):
        async with db_session.begin_nested():
            await db_session.execute(text("UPDATE prestamos SET moneda = 'USD'"))

    # Tampoco la de una línea que ya tiene préstamos.
    cambio = await staff.put(
        f"/api/v1/prestamos/lineas/{linea['id']}",
        json={**{k: v for k, v in linea.items() if k != "id"}, "moneda": "USD"},
    )
    assert cambio.status_code == 409
    assert "moneda no cambia" in cambio.json()["detail"]


async def test_una_linea_sin_prestamos_puede_cambiar_de_moneda(
    staff: AsyncClient, crear_linea: Callable[..., Any]
) -> None:
    linea = await crear_linea()
    cambio = await staff.put(
        f"/api/v1/prestamos/lineas/{linea['id']}",
        json={**{k: v for k, v in linea.items() if k != "id"}, "moneda": "USD"},
    )
    assert cambio.status_code == 200, cambio.text
    assert cambio.json()["moneda"] == "USD"


async def test_antiguedad_en_la_matricula(
    staff: AsyncClient,
    escenario: Escenario,
    crear_linea: Callable[..., Any],
    reloj: Callable[[date], None],
    db_session: AsyncSession,
) -> None:
    linea = await crear_linea(antiguedad_minima_meses=12)
    cuerpo = {
        "linea_id": linea["id"],
        "capital": "100000",
        "cuotas": 12,
        "ingreso_neto": "60000",
        "escribano_id": str(escenario.titular.id),
    }
    # Matriculado en 2010: cumple.
    ok = (await staff.post("/api/v1/prestamos/simular", json=cuerpo)).json()
    assert ok["impedimentos"] == []

    escenario.titular.fecha_matriculacion = date(2026, 1, 15)
    await db_session.commit()
    nuevo = (await staff.post("/api/v1/prestamos/simular", json=cuerpo)).json()
    assert nuevo["impedimentos"] == [
        "La línea exige 1 año de antigüedad en la matrícula (matriculación: 15/01/2026)."
    ]
    rechazada = await staff.post("/api/v1/prestamos", json=solicitud(escenario, linea))
    assert rechazada.status_code == 422


async def test_antiguedad_no_verificable_sin_fecha(db_session: AsyncSession) -> None:
    """Sin fecha de matriculación no se bloquea: queda un aviso para quien resuelve."""
    linea = Linea(
        id=uuid.uuid4(),
        codigo="ANTIGUEDAD_PRUEBA",
        nombre="Antigüedad",
        sistema="FRANCES",
        plazo_minimo=1,
        plazo_maximo=12,
        monto_minimo=D("0.01"),
        monto_maximo=D("1000000.00"),
        tna=D("30.0000"),
        afectacion_maxima=D("30.0000"),
        moneda="ARS",
        antiguedad_minima_meses=12,
        requiere_garante=False,
        es_ejemplo=False,
        is_active=True,
    )
    # Escribano en memoria (no se guarda): la columna todavía es obligatoria en la base.
    escribano = Escribano(id=uuid.uuid4(), estado_matricula="ACTIVO", fecha_matriculacion=None)
    ev = await service.evaluar(
        db_session,
        linea,
        capital=D("100000"),
        cuotas=12,
        hoy=HOY,
        escribano=escribano,
        ingreso_neto=D("60000"),
        garante_id=None,
    )
    assert ev.impedimentos == []
    assert ev.avisos == [service.ANTIGUEDAD_NO_VERIFICABLE]
    assert service.antiguedad_suficiente(date(2025, 10, 23), 12, HOY)
    assert not service.antiguedad_suficiente(date(2025, 10, 24), 12, HOY)
