"""Una boleta por escribano (contrato, Anexo I): cada notario del registro paga la suya.

Titular y adscripto pagan cada uno su mínimo, su aporte médico y el excedente sobre sus actos.
Quien está a cargo paga lo que fijó la Caja en su designación.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.ddjj.catalog import CategoriaActo, ModalidadBoleta
from app.modules.ddjj.liquidacion import (
    ACTO_SIN_CARGO,
    SIN_TITULAR_UNICO,
    ActoALiquidar,
    LiquidacionError,
    Obligado,
    liquidar_por_escribano,
)
from app.modules.padron.models import Adscripcion
from app.modules.parametros.catalog import ReglaRedondeo, TipoConcepto
from app.modules.parametros.motor import VigenciaSnapshot
from tests.ddjj.conftest import Escenario, escritura
from tests.ddjj.test_a_cargo import Designado, designado  # noqa: F401 - fixture
from tests.ddjj.test_flujo import _borrador, _presentar, _reemitir

D = Decimal
MINIMO = "85932.00"
MEDICO = "97000.00"


async def _liquidacion(client: AsyncClient, ddjj_id: str, fecha_pago: str = "2026-10-23") -> Any:
    response = await client.get(
        f"/api/v1/ddjj/declaraciones/{ddjj_id}/liquidacion", params={"fecha_pago": fecha_pago}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _cargar(client: AsyncClient, ddjj_id: str, *actos: dict[str, Any]) -> None:
    for acto in actos:
        response = await client.post(f"/api/v1/ddjj/declaraciones/{ddjj_id}/actos", json=acto)
        assert response.status_code == 201, response.text


async def test_cada_escribano_paga_su_boleta(
    notario: AsyncClient,
    staff: AsyncClient,
    client: AsyncClient,
    escenario: Escenario,
    db_session: AsyncSession,
) -> None:
    ddjj = await _borrador(notario, escenario)
    await _cargar(
        notario,
        ddjj["id"],
        escritura(escenario.titular, 1, "100000000.00"),  # aporte 400.000
        escritura(escenario.adscripto, 2, "120000000.00"),  # aporte 480.000
    )

    preview = await _liquidacion(notario, ddjj["id"])
    titular, adscripto = preview["boletas"]
    # Cada uno: su excedente sobre sus propios actos, su mínimo y su aporte médico.
    assert titular["escribano"]["id"] == str(escenario.titular.id)
    assert (titular["total_protocolos"], titular["excedente"]) == ("400000.00", "314068.00")
    assert titular["total_a_pagar"] == "497000.00"
    assert adscripto["escribano"]["id"] == str(escenario.adscripto.id)
    assert (adscripto["total_protocolos"], adscripto["excedente"]) == ("480000.00", "394068.00")
    assert adscripto["total_a_pagar"] == "577000.00"
    for b in (titular, adscripto):
        assert (b["aporte_minimo"], b["aporte_medico"]) == (MINIMO, MEDICO)
    assert preview["total_protocolos"] == "880000.00"
    assert preview["total_a_pagar"] == "1074000.00"

    emitidas = await _presentar(notario, ddjj["id"])
    assert [b["total_a_pagar"] for b in emitidas] == ["497000.00", "577000.00"]
    del_titular, del_adscripto = emitidas
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert detalle["total_protocolos"] == "880000.00"

    # Reemitir anula la pendiente: el titular no puede reemitir la del adscripto.
    ajena = await _reemitir(notario, ddjj["id"], escenario.adscripto, "2026-11-07")
    assert ajena.status_code == 403
    assert [b["puede_reemitir"] for b in emitidas] == [True, False]
    vistas_por_la_caja = (await staff.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert all(b["puede_reemitir"] for b in vistas_por_la_caja["boletas"])

    # El adscripto paga en otra fecha (la reemite la Caja; él no tiene usuario en este
    # escenario) y la del titular no cambia.
    tarde = await _reemitir(staff, ddjj["id"], escenario.adscripto, "2026-11-07")
    assert tarde.status_code == 201, tarde.text
    assert tarde.json()["escribano"]["id"] == str(escenario.adscripto.id)
    assert tarde.json()["dias_mora"] == 10
    assert D(tarde.json()["interes_mora"]) > 0
    estados = {
        b["numero"]: b["estado"]
        for b in (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()["boletas"]
    }
    assert estados == {
        del_titular["numero"]: "PENDIENTE",
        del_adscripto["numero"]: "ANULADA",
        tarde.json()["numero"]: "PENDIENTE",
    }

    # Sin decir de quién, no hay boleta del registro que reemitir.
    sin_escribano = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/boletas", json={"fecha_pago": "2026-10-27"}
    )
    assert sin_escribano.status_code == 409

    # Cada boleta verifica por su cuenta y su PDF es la del escribano.
    for b in (del_titular, tarde.json()):
        verificacion = await client.get(f"/api/v1/boletas/verificar/{b['codigo_verificacion']}")
        assert verificacion.json()["integra"] is True
        pdf = await notario.get(f"/api/v1/ddjj/boletas/{b['id']}/pdf")
        assert pdf.status_code == 200

    emitidas_auditadas = (
        await db_session.scalars(
            select(AuditSecurityLog.details).where(AuditSecurityLog.event_type == "BOLETA_EMITIDA")
        )
    ).all()
    assert {d["escribano_id"] for d in emitidas_auditadas if d} == {
        str(escenario.titular.id),
        str(escenario.adscripto.id),
    }


async def _designar_septiembre(staff: AsyncClient, e: Escenario, d: Designado) -> dict[str, Any]:
    response = await staff.post(
        "/api/v1/a-cargo",
        json={
            "registro_id": str(e.registro.id),
            "escribano_id": str(d.escribano.id),
            "fecha_desde": "2026-09-01",
            "fecha_hasta": "2026-09-30",
            "motivo": "Licencia del titular",
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["estado"] == "APROBADA"
    assert body["aporte"] == "SOLO_ACTOS"
    return body


async def _fijar_aporte(client: AsyncClient, designacion_id: str, aporte: str) -> Any:
    return await client.post(
        f"/api/v1/a-cargo/{designacion_id}/aporte",
        json={"aporte": aporte, "motivo": "Resolución de la Caja"},
    )


@pytest.mark.parametrize(
    ("aporte", "boleta_a_cargo", "protocolos_titular"),
    [
        # Solo sus actos: 400.000, sin mínimo ni médico.
        ("SOLO_ACTOS", ("SOLO_ACTOS", "0.00", "0.00", "400000.00"), "0.00"),
        # Mínimo y excedente sobre sus actos, sin médico: 85.932 + 314.068.
        ("CON_MINIMO", ("CON_MINIMO", MINIMO, "0.00", "400000.00"), "0.00"),
        # Sin boleta propia: sus actos van a la del titular.
        ("EN_BOLETA_DEL_TITULAR", None, "400000.00"),
    ],
)
async def test_el_escribano_a_cargo_paga_lo_que_fija_la_caja(
    staff: AsyncClient,
    escenario: Escenario,
    designado: Designado,  # noqa: F811
    aporte: str,
    boleta_a_cargo: tuple[str, str, str, str] | None,
    protocolos_titular: str,
) -> None:
    designacion = await _designar_septiembre(staff, escenario, designado)
    if aporte != "SOLO_ACTOS":
        fijado = await _fijar_aporte(staff, designacion["id"], aporte)
        assert fijado.status_code == 200, fijado.text
        assert fijado.json()["aporte"] == aporte
    ddjj = await _borrador(staff, escenario)
    await _cargar(staff, ddjj["id"], escritura(designado.escribano, 1, "100000000.00"))

    emitidas = {b["escribano"]["cargo"]: b for b in await _presentar(staff, ddjj["id"])}

    assert emitidas["TITULAR"]["total_protocolos"] == protocolos_titular
    assert emitidas["ADSCRIPTO"]["total_protocolos"] == "0.00"
    if boleta_a_cargo is None:
        assert set(emitidas) == {"TITULAR", "ADSCRIPTO"}
    else:
        b = emitidas["SUPLENTE_INTERINO"]
        assert b["escribano"]["id"] == str(designado.escribano.id)
        assert (
            b["escribano"]["modalidad"],
            b["aporte_minimo"],
            b["aporte_medico"],
            b["total_a_pagar"],
        ) == boleta_a_cargo
        assert b["cantidad_aportes_medicos"] == 0


async def test_cambiar_el_aporte_no_altera_las_boletas_emitidas(
    staff: AsyncClient,
    escenario: Escenario,
    designado: Designado,  # noqa: F811
) -> None:
    designacion = await _designar_septiembre(staff, escenario, designado)
    ddjj = await _borrador(staff, escenario)
    await _cargar(staff, ddjj["id"], escritura(designado.escribano, 1, "100000000.00"))
    a_cargo = next(
        b
        for b in await _presentar(staff, ddjj["id"])
        if b["escribano"]["cargo"] == "SUPLENTE_INTERINO"
    )

    assert (await _fijar_aporte(staff, designacion["id"], "CON_MINIMO")).status_code == 200

    # La emitida no cambia y la reemisión conserva la modalidad con que se emitió (SNAP).
    leida = (await staff.get(f"/api/v1/ddjj/boletas/{a_cargo['id']}")).json()
    assert leida["escribano"]["modalidad"] == "SOLO_ACTOS"
    assert leida["total_a_pagar"] == "400000.00"
    reemitida = await _reemitir(staff, ddjj["id"], designado.escribano, "2026-10-27")
    assert reemitida.status_code == 201, reemitida.text
    assert reemitida.json()["escribano"]["modalidad"] == "SOLO_ACTOS"
    assert reemitida.json()["aporte_minimo"] == "0.00"


async def test_solo_la_caja_fija_el_aporte(
    notario: AsyncClient,
    staff: AsyncClient,
    escenario: Escenario,
    designado: Designado,  # noqa: F811
    db_session: AsyncSession,
) -> None:
    designacion = await _designar_septiembre(staff, escenario, designado)
    vista = (await notario.get(f"/api/v1/a-cargo/{designacion['id']}")).json()
    assert vista["aporte"] == "SOLO_ACTOS"
    assert vista["puede_fijar_aporte"] is False

    assert (await _fijar_aporte(notario, designacion["id"], "CON_MINIMO")).status_code == 403
    sin_motivo = await staff.post(
        f"/api/v1/a-cargo/{designacion['id']}/aporte", json={"aporte": "CON_MINIMO"}
    )
    assert sin_motivo.status_code == 422
    assert (await _fijar_aporte(staff, designacion["id"], "OTRA_COSA")).status_code == 422
    assert (await _fijar_aporte(staff, designacion["id"], "SOLO_ACTOS")).status_code == 409
    ok = await _fijar_aporte(staff, designacion["id"], "CON_MINIMO")
    assert ok.status_code == 200, ok.text

    log = await db_session.scalar(
        select(AuditSecurityLog).where(
            AuditSecurityLog.event_type == "PADRON_A_CARGO_APORTE_FIJADO"
        )
    )
    assert log is not None and log.old_value and log.new_value and log.details
    assert (log.old_value["aporte"], log.new_value["aporte"]) == ("SOLO_ACTOS", "CON_MINIMO")
    assert log.details["motivo"] == "Resolución de la Caja"


async def test_minimo_completo_y_aviso_si_el_cargo_termina_en_el_mes(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Adscripcion)
        .where(Adscripcion.escribano_id == escenario.adscripto.id)
        .values(fecha_hasta=date(2026, 9, 15), is_current=False, motivo_cierre="Renuncia")
    )
    await db_session.commit()
    ddjj = await _borrador(notario, escenario)

    preview = await _liquidacion(notario, ddjj["id"])

    adscripto = preview["boletas"][1]
    assert adscripto["aporte_minimo"] == MINIMO  # completo: la Caja no definió el proporcional
    (aviso,) = preview["avisos"]
    assert aviso.startswith("ADSCRIPTO, ")
    assert "termina su cargo dentro del período" in aviso


async def test_el_escribano_de_la_boleta_no_cambia_en_la_base(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    ddjj = await _borrador(notario, escenario)
    await _presentar(notario, ddjj["id"])

    for sentencia, valores in (
        ("UPDATE ddjj_boletas SET escribano_id = :otro", {"otro": escenario.adscripto.id}),
        ("UPDATE ddjj_boletas SET modalidad = 'SOLO_ACTOS'", {}),
    ):
        with pytest.raises(DBAPIError, match="el escribano de una boleta emitida no cambia"):
            async with db_session.begin_nested():
                await db_session.execute(text(sentencia), valores)


# --------------------------------------------------------------------------- cálculo puro


def _vigencia(monto: str) -> VigenciaSnapshot:
    return VigenciaSnapshot(
        vigencia_id=uuid.uuid4(),
        concepto_codigo="X",
        tipo=TipoConcepto.FIJO_MENSUAL,
        fecha_desde=date(2026, 1, 1),
        fecha_hasta=None,
        porcentaje=None,
        monto_fijo=D(monto),
        monto_minimo=None,
        monto_maximo=None,
        tasa=None,
        periodo_tasa=None,
        dias_gracia=None,
        regla_redondeo=ReglaRedondeo.HALF_UP,
    )


def _liquidar(actos: list[Any], equipo: list[Obligado]) -> Any:
    return liquidar_por_escribano(
        actos,
        equipo,
        minimo=_vigencia("100.00"),
        medico=_vigencia("10.00"),
        vencimiento=date(2026, 10, 28),
        fecha_pago=date(2026, 10, 23),
        mora=[],
    )


def test_a_cargo_en_boleta_del_titular_exige_un_unico_titular() -> None:
    a_cargo = Obligado(uuid.uuid4(), "SUPLENTE_INTERINO", None)
    acto = (a_cargo.escribano_id, ActoALiquidar(CategoriaActo.ACTA_O_PODER, D(0)), _vigencia("5"))
    with pytest.raises(LiquidacionError, match=SIN_TITULAR_UNICO):
        _liquidar([acto], [a_cargo])
    titulares = [Obligado(uuid.uuid4(), "TITULAR", ModalidadBoleta.COMPLETA) for _ in range(2)]
    with pytest.raises(LiquidacionError, match=SIN_TITULAR_UNICO):
        _liquidar([acto], [*titulares, a_cargo])
    _, boletas = _liquidar([acto], [titulares[0], a_cargo])
    (b,) = boletas
    assert b.obligado == titulares[0]
    assert (b.liquidacion.total_protocolos, b.liquidacion.total_en_termino) == (
        D("5.00"),
        D("110.00"),
    )


def test_actos_de_quien_no_integra_el_registro() -> None:
    titular = Obligado(uuid.uuid4(), "TITULAR", ModalidadBoleta.COMPLETA)
    ajeno = (uuid.uuid4(), ActoALiquidar(CategoriaActo.ACTA_O_PODER, D(0)), _vigencia("5"))
    with pytest.raises(LiquidacionError, match=ACTO_SIN_CARGO):
        _liquidar([ajeno], [titular])
    with pytest.raises(LiquidacionError, match="dos veces"):
        _liquidar([], [titular, titular])


def test_a_cargo_solo_por_actos_sin_nada_que_aportar_no_tiene_boleta() -> None:
    titular = Obligado(uuid.uuid4(), "TITULAR", ModalidadBoleta.COMPLETA)
    a_cargo = Obligado(uuid.uuid4(), "SUPLENTE_INTERINO", ModalidadBoleta.SOLO_ACTOS)
    exento = (a_cargo.escribano_id, ActoALiquidar(CategoriaActo.EXENTO, D(0)), None)
    aportes, boletas = _liquidar([exento], [titular, a_cargo])
    assert [a.aporte for a in aportes] == [D("0.00")]
    assert [b.obligado for b in boletas] == [titular]
