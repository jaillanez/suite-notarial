"""DDJJ de punta a punta: borrador, actos, liquidación, presentación, boleta, PDF y verificación."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.padron.models import Adscripcion
from app.modules.parametros.models import Concepto, Vigencia
from tests.ddjj.conftest import Escenario, escritura

D = Decimal


async def _solo_titular(db_session: AsyncSession, e: Escenario) -> None:
    """Como en la boleta 1069: el registro tiene solo al titular en septiembre."""
    await db_session.execute(
        update(Adscripcion)
        .where(Adscripcion.escribano_id == e.adscripto.id)
        .values(fecha_hasta=date(2026, 8, 31), is_current=False, motivo_cierre="Prueba")
    )
    await db_session.commit()


async def _borrador(client: AsyncClient, e: Escenario, periodo: str = "2026-09") -> dict[str, Any]:
    response = await client.post(
        "/api/v1/ddjj/declaraciones", json={"registro_id": str(e.registro.id), "periodo": periodo}
    )
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


async def _cargar_1069(client: AsyncClient, e: Escenario) -> dict[str, Any]:
    ddjj = await _borrador(client, e)
    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos"
    for numero, base in ((101, "100000000.00"), (102, "120000000.00"), (103, "26174765.00")):
        response = await client.post(url, json=escritura(e.titular, numero, base))
        assert response.status_code == 201, response.text
    return ddjj


async def _presentar(
    client: AsyncClient, ddjj_id: str, fecha_pago: str = "2026-10-23"
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/ddjj/declaraciones/{ddjj_id}/presentar", json={"fecha_pago": fecha_pago}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_boleta_1069_de_punta_a_punta(
    notario: AsyncClient, client: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    await _solo_titular(db_session, escenario)
    ddjj = await _cargar_1069(notario, escenario)

    preview = (
        await notario.get(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion",
            params={"fecha_pago": "2026-10-23"},
        )
    ).json()
    boleta = await _presentar(notario, ddjj["id"])

    for liq in (preview, boleta):
        assert liq["total_protocolos"] == "984699.06"
        assert liq["aporte_minimo"] == "85932.00"
        assert liq["excedente"] == "898767.06"
        assert liq["aporte_medico"] == "97000.00"
        assert liq["total_en_termino"] == "1081699.06"
        assert liq["interes_mora"] == "0.00"
        assert liq["total_a_pagar"] == "1081699.06"
    assert [a["aporte"] for a in preview["aportes"]] == ["400000.00", "480000.00", "104699.06"]
    assert preview["usa_valores_de_ejemplo"] is False
    assert boleta["fecha_vencimiento"] == "2026-10-28"
    assert boleta["estado"] == "PENDIENTE"

    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert detalle["estado"] == "PRESENTADA"
    assert detalle["total_protocolos"] == "984699.06"
    assert [a["aporte"] for a in detalle["actos"]] == ["400000.00", "480000.00", "104699.06"]
    assert all(a["vigencia_id"] for a in detalle["actos"])

    pdf = await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    # Verificación pública, sin sesión y sin datos personales.
    verificacion = await client.get(f"/api/v1/boletas/verificar/{boleta['codigo_verificacion']}")
    assert verificacion.status_code == 200
    body = verificacion.json()
    assert body["integra"] is True
    assert body["total_a_pagar"] == "1081699.06"
    assert body["registro_numero"] == escenario.registro.numero_registro
    assert "escribano" not in str(body).lower()

    eventos = set(
        (
            await db_session.scalars(
                select(AuditSecurityLog.event_type).where(
                    AuditSecurityLog.event_type.in_(["DDJJ_PRESENTADA", "BOLETA_EMITIDA"])
                )
            )
        ).all()
    )
    assert eventos == {"DDJJ_PRESENTADA", "BOLETA_EMITIDA"}


async def test_aporte_medico_por_titular_y_adscripto(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario)

    boleta = await _presentar(notario, ddjj["id"])

    # Sin actos: rige el mínimo. Dos escribanos con cargo propio: dos aportes médicos.
    assert boleta["total_protocolos"] == "0.00"
    assert boleta["cantidad_aportes_medicos"] == 2
    assert boleta["aporte_medico"] == "194000.00"
    assert boleta["total_a_pagar"] == "279932.00"


async def test_cambio_de_parametros_no_altera_lo_emitido(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    await _solo_titular(db_session, escenario)
    ddjj = await _cargar_1069(notario, escenario)
    original = await _presentar(notario, ddjj["id"])

    # Nueva vigencia del mínimo desde septiembre (cierra la anterior).
    concepto_id = await db_session.scalar(
        select(Concepto.id).where(Concepto.codigo == "APORTE_MINIMO_MENSUAL")
    )
    abierta = await db_session.scalar(
        select(Vigencia).where(Vigencia.concepto_id == concepto_id, Vigencia.fecha_hasta.is_(None))
    )
    assert abierta is not None
    abierta.fecha_hasta = date(2026, 8, 31)
    await db_session.flush()
    db_session.add(
        Vigencia(
            concepto_id=concepto_id,
            version=99,
            fecha_desde=date(2026, 9, 1),
            monto_fijo=D("999999.00"),
            estado="VIGENTE",
            resolucion_respaldo="Prueba",
            motivo="Cambio de parámetro",
            created_by_user_id=abierta.created_by_user_id,
            aprobado_por_user_id=abierta.aprobado_por_user_id,
        )
    )
    await db_session.commit()

    leida = (await notario.get(f"/api/v1/ddjj/boletas/{original['id']}")).json()
    reemitida = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/boletas", json={"fecha_pago": "2026-10-27"}
    )

    assert leida["aporte_minimo"] == "85932.00"
    assert leida["total_a_pagar"] == "1081699.06"
    assert reemitida.status_code == 201, reemitida.text
    assert reemitida.json()["aporte_minimo"] == "85932.00"
    assert reemitida.json()["total_a_pagar"] == "1081699.06"


async def test_reemision_fuera_de_termino_aplica_la_mora_y_anula_la_anterior(
    notario: AsyncClient, client: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    await _solo_titular(db_session, escenario)
    ddjj = await _cargar_1069(notario, escenario)
    original = await _presentar(notario, ddjj["id"])

    response = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/boletas", json={"fecha_pago": "2026-11-07"}
    )

    assert response.status_code == 201, response.text
    nueva = response.json()
    # Vence el 28/10; pagando el 07/11 son 10 días a la tasa vigente (4,25 % mensual, mes de
    # 30 días, interés simple: confirmada por la Caja).
    esperado = (D("1081699.06") * D("4.25") / D(100) / D(30) * D(10)).quantize(D("0.01"))
    assert nueva["dias_mora"] == 10
    assert nueva["interes_mora"] == f"{esperado:.2f}" == "15324.07"
    assert D(nueva["total_a_pagar"]) == D("1081699.06") + esperado
    assert nueva["numero"] == original["numero"] + 1
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    estados = {b["numero"]: b["estado"] for b in detalle["boletas"]}
    assert estados == {original["numero"]: "ANULADA", nueva["numero"]: "PENDIENTE"}
    anulada = await client.get(f"/api/v1/boletas/verificar/{original['codigo_verificacion']}")
    assert anulada.json()["estado"] == "ANULADA"


@pytest.mark.ejemplo("TASA_INTERES_MORA")
async def test_la_vista_previa_avisa_valores_de_ejemplo(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario)

    preview = await notario.get(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion",
        params={"fecha_pago": "2026-11-07"},
    )

    # La tasa de mora de este test está marcada "a confirmar".
    assert preview.status_code == 200, preview.text
    assert preview.json()["dias_mora"] == 10
    assert preview.json()["usa_valores_de_ejemplo"] is True


async def test_rectificativa(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    await _solo_titular(db_session, escenario)
    ddjj = await _cargar_1069(notario, escenario)
    original = await _presentar(notario, ddjj["id"])

    response = await notario.post(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/rectificar")

    assert response.status_code == 201, response.text
    rect = response.json()
    assert rect["estado"] == "BORRADOR"
    assert rect["numero_rectificativa"] == 1
    assert rect["rectifica_a_id"] == ddjj["id"]
    assert len(rect["actos"]) == 3
    assert all(a["aporte"] is None for a in rect["actos"])
    vieja = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert vieja["estado"] == "RECTIFICADA"
    assert vieja["boletas"][0]["estado"] == "ANULADA"
    assert vieja["boletas"][0]["numero"] == original["numero"]

    acta = {
        **escritura(escenario.titular, 104, "0"),
        "categoria": "ACTA_O_PODER",
        "naturaleza": "Poder general",
    }
    added = await notario.post(f"/api/v1/ddjj/declaraciones/{rect['id']}/actos", json=acta)
    assert added.status_code == 201, added.text
    nueva = await _presentar(notario, rect["id"])
    assert nueva["total_protocolos"] == "994621.06"  # + 9.922 del poder
    assert nueva["numero_rectificativa"] == 1


async def test_borrador_es_unico_y_baja_de_actos(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    primero = await _borrador(notario, escenario)
    segundo = await _borrador(notario, escenario)
    assert primero["id"] == segundo["id"]

    url = f"/api/v1/ddjj/declaraciones/{primero['id']}/actos"
    acto = (await notario.post(url, json=escritura(escenario.titular, 1, "1000.00"))).json()
    baja = await notario.post(f"{url}/{acto['id']}/baja", json={"motivo": "Cargado por error"})
    again = await notario.post(url, json=escritura(escenario.titular, 1, "2000.00"))

    assert baja.status_code == 204
    assert again.status_code == 201  # el número queda libre tras la baja
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{primero['id']}")).json()
    assert [a["base_imponible"] for a in detalle["actos"]] == ["2000.00"]
    audit = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "DDJJ_ACTO_BAJA")
    )
    assert audit is not None and audit.details is not None
    assert audit.details["motivo"] == "Cargado por error"


async def test_validaciones_de_actos(notario: AsyncClient, escenario: Escenario) -> None:
    ddjj = await _borrador(notario, escenario)
    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos"
    t = escenario.titular

    fuera = await notario.post(url, json=escritura(t, 1, "1000.00", fecha_acto="2026-08-31"))
    sin_base = await notario.post(url, json=escritura(t, 2, "0"))
    poder_con_base = await notario.post(
        url, json={**escritura(t, 3, "500.00"), "categoria": "ACTA_O_PODER"}
    )
    ajeno = await notario.post(
        url, json={**escritura(t, 4, "1000.00"), "escribano_id": str(uuid.uuid4())}
    )
    ok = await notario.post(url, json=escritura(t, 5, "1000.00"))
    duplicado = await notario.post(url, json=escritura(t, 5, "3000.00"))
    auxiliar = await notario.post(url, json=escritura(t, 5, "3000.00", tipo_protocolo="AUXILIAR"))

    assert fuera.status_code == 422
    assert sin_base.status_code == 422
    assert poder_con_base.status_code == 422
    assert ajeno.status_code == 422
    assert ok.status_code == 201
    assert duplicado.status_code == 409
    assert auxiliar.status_code == 201


async def test_reglas_de_presentacion(notario: AsyncClient, escenario: Escenario) -> None:
    en_curso = await _borrador(notario, escenario, "2026-10")
    futuro = await notario.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.registro.id), "periodo": "2026-11"},
    )
    presentar_en_curso = await notario.post(
        f"/api/v1/ddjj/declaraciones/{en_curso['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    ddjj = await _borrador(notario, escenario)
    pasado = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-22"}
    )
    lejano = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2027-01-30"}
    )
    await _presentar(notario, ddjj["id"])
    tarde = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos",
        json=escritura(escenario.titular, 1, "1000.00"),
    )

    assert futuro.status_code == 422
    assert presentar_en_curso.status_code == 422
    assert pasado.status_code == 422
    assert lejano.status_code == 422
    assert tarde.status_code == 409


async def test_sin_vencimiento_cargado(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    ddjj = await _borrador(notario, escenario, "2025-12")

    response = await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion")

    assert response.status_code == 422
    assert response.json()["type"] == "urn:suite-notarial:ddjj:sin-vencimiento"
