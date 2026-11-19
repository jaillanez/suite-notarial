"""DDJJ del sistema anterior: consulta de solo lectura del histórico migrado."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.migracion.models import Corrida, HistoricoActo, HistoricoBoleta, HistoricoPago
from tests.ddjj.conftest import Escenario
from tests.iam.factories import make_user

D = Decimal


@pytest.fixture
async def historico(db_session: AsyncSession, escenario: Escenario) -> None:
    """Registro del escenario: 2025-09 con dos actos y la boleta pagada; 2025-10 sin actos y con
    la boleta impaga. El otro registro (ajeno al titular) tiene una DDJJ en 2025-09."""
    operador = await make_user(db_session)
    corrida = Corrida(
        id=uuid.uuid4(),
        modo="SIMULACRO",
        estado="EN_CURSO",
        huella_lote="0" * 64,
        version_formato="1",
        homologacion="prueba",
        homologacion_ejemplo=True,
        huella_homologacion="0" * 64,
        homologacion_tablas={},
        operador_user_id=operador.id,
    )
    db_session.add(corrida)
    await db_session.flush()
    await db_session.execute(text("SET LOCAL suite.migracion = 'on'"))
    actos = [
        (escenario.registro.id, "2025-09", 101, "Compraventa", D("50000000.00"), D("200000.00")),
        (escenario.registro.id, "2025-09", 102, "Poder general", None, D("9922.00")),
        (escenario.otro_registro.id, "2025-09", 7, "Donación", None, D("37446.00")),
    ]
    for i, (registro_id, periodo, numero, naturaleza, base, importe) in enumerate(actos):
        db_session.add(
            HistoricoActo(
                id=uuid.uuid4(),
                corrida_id=corrida.id,
                codigo_legado=f"A-{i}-{uuid.uuid4().hex[:6]}",
                registro_id=registro_id,
                escribano_origen="ORIGEN, Escribano",
                periodo=periodo,
                fecha_acto=date(2025, 9, 10),
                tipo_protocolo="GENERAL",
                numero_escritura=numero,
                naturaleza=naturaleza,
                base_imponible=base,
                importe=importe,
            )
        )
    for periodo, estado, pagos in (
        ("2025-09", "PAGADA", [(date(2025, 10, 10), "295854.00")]),
        ("2025-10", "IMPAGA", []),
    ):
        boleta = HistoricoBoleta(
            id=uuid.uuid4(),
            corrida_id=corrida.id,
            codigo_legado=f"B-{periodo}-{uuid.uuid4().hex[:6]}",
            registro_id=escenario.registro.id,
            periodo=periodo,
            numero_boleta=f"L-{periodo}",
            fecha_emision=date(int(periodo[:4]), int(periodo[5:]), 28),
            fecha_vencimiento=date(int(periodo[:4]), int(periodo[5:]), 28),
            importe=D("295854.00"),
            estado=estado,
        )
        db_session.add(boleta)
        await db_session.flush()
        for j, (fecha, monto) in enumerate(pagos):
            db_session.add(
                HistoricoPago(
                    id=uuid.uuid4(),
                    corrida_id=corrida.id,
                    codigo_legado=f"P-{boleta.codigo_legado}-{j}",
                    boleta_id=boleta.id,
                    fecha_pago=fecha,
                    importe=D(monto),
                )
            )
    await db_session.flush()


async def test_la_caja_ve_todas_las_ddjj_anteriores(
    historico: None, staff: AsyncClient, escenario: Escenario
) -> None:
    r = await staff.get("/api/v1/ddjj/anteriores")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["total"] == 3
    # De la más reciente a la más vieja.
    assert [i["periodo"] for i in cuerpo["items"]] == ["2025-10", "2025-09", "2025-09"]
    sep = next(
        i
        for i in cuerpo["items"]
        if i["periodo"] == "2025-09" and i["registro_id"] == str(escenario.registro.id)
    )
    assert sep["cantidad_actos"] == 2
    assert D(sep["total_aportes"]) == D("209922.00")
    assert D(sep["total_boletas"]) == D("295854.00")
    assert D(sep["total_pagado"]) == D("295854.00")
    # Un mes sin actos pero con boleta también figura.
    octubre = cuerpo["items"][0]
    assert octubre["cantidad_actos"] == 0 and D(octubre["total_pagado"]) == 0
    # Filtros por registro y período.
    filtrado = await staff.get(
        "/api/v1/ddjj/anteriores",
        params={"registro": escenario.otro_registro.numero_registro, "periodo": "2025-09"},
    )
    assert filtrado.json()["total"] == 1


async def test_el_detalle_trae_actos_y_boletas(
    historico: None, staff: AsyncClient, escenario: Escenario
) -> None:
    r = await staff.get(f"/api/v1/ddjj/anteriores/{escenario.registro.id}/2025-09")
    assert r.status_code == 200, r.text
    detalle = r.json()
    assert [a["numero_escritura"] for a in detalle["actos"]] == [101, 102]
    assert detalle["actos"][0]["escribano"] == "ORIGEN, Escribano"
    (boleta,) = detalle["boletas"]
    assert boleta["estado"] == "PAGADA" and boleta["fecha_pago"] == "2025-10-10"
    assert (
        await staff.get(f"/api/v1/ddjj/anteriores/{escenario.registro.id}/2024-01")
    ).status_code == 404


async def test_el_escribano_solo_ve_las_de_su_registro(
    historico: None, notario: AsyncClient, escenario: Escenario
) -> None:
    r = await notario.get("/api/v1/ddjj/anteriores")
    assert r.status_code == 200, r.text
    assert {i["registro_id"] for i in r.json()["items"]} == {str(escenario.registro.id)}
    ajena = await notario.get(f"/api/v1/ddjj/anteriores/{escenario.otro_registro.id}/2025-09")
    assert ajena.status_code == 404


async def test_sin_sesion_no_se_consulta(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/ddjj/anteriores")).status_code == 401
