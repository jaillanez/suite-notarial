"""Actos exentos: se declaran con motivo, no aportan y el mínimo mensual se cobra igual."""

from typing import Any

from httpx import AsyncClient

from tests.ddjj.conftest import Escenario, escritura
from tests.ddjj.test_protocolo import _agregar, _borrador


def _exento(e: Escenario, numero: int, **extra: Any) -> dict[str, Any]:
    return escritura(e.titular, numero, "0", categoria="EXENTO", **extra)


async def test_exento_exige_motivo(notario: AsyncClient, escenario: Escenario) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")

    sin_motivo = await _agregar(notario, ddjj["id"], _exento(escenario, 1))
    assert sin_motivo.status_code == 422
    otro_sin_detalle = await _agregar(
        notario, ddjj["id"], _exento(escenario, 1, motivo_exencion="OTRO", detalle_exencion="  ")
    )
    assert otro_sin_detalle.status_code == 422
    # El motivo es solo para los exentos.
    con_valor = escritura(escenario.titular, 1, "1000", motivo_exencion="CONVENIO_IPV")
    assert (await _agregar(notario, ddjj["id"], con_valor)).status_code == 422
    # Un exento no lleva base imponible.
    con_base = _exento(escenario, 1, motivo_exencion="CONVENIO_IPV", base_imponible="1000")
    assert (await _agregar(notario, ddjj["id"], con_base)).status_code == 422

    otro = await _agregar(
        notario,
        ddjj["id"],
        _exento(escenario, 1, motivo_exencion="OTRO", detalle_exencion="Donación al Estado"),
    )
    assert otro.status_code == 201, otro.text
    assert otro.json()["motivo_exencion"] == "OTRO"
    assert otro.json()["detalle_exencion"] == "Donación al Estado"


async def test_exento_no_aporta_pero_cuenta_y_se_cobra_el_minimo(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    for numero, motivo in ((1, "CONVENIO_IPV"), (2, "ACTA_SUBSANATORIA")):
        response = await _agregar(
            notario, ddjj["id"], _exento(escenario, numero, motivo_exencion=motivo)
        )
        assert response.status_code == 201, response.text
        assert response.json()["detalle_exencion"] is None

    liq = (
        await notario.get(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion",
            params={"fecha_pago": "2026-10-23"},
        )
    ).json()
    assert [a["aporte"] for a in liq["aportes"]] == ["0.00", "0.00"]
    assert liq["total_protocolos"] == "0.00"
    assert liq["excedente"] == "0.00"
    assert liq["aporte_minimo"] != "0.00"
    presentada = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    assert presentada.status_code == 201, presentada.text
    assert presentada.json()["total_en_termino"] == liq["total_en_termino"]

    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert detalle["cantidad_actos"] == 2
    # La rectificativa conserva el motivo.
    rect = (await notario.post(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/rectificar")).json()
    assert sorted(a["motivo_exencion"] for a in rect["actos"]) == [
        "ACTA_SUBSANATORIA",
        "CONVENIO_IPV",
    ]


async def test_detalle_vacio_en_un_acto_que_no_es_exento(
    notario: AsyncClient, escenario: Escenario
) -> None:
    """Un detalle en blanco cuenta como ausente: no llega a la base como texto vacío."""
    ddjj = await _borrador(notario, escenario, "2026-09")
    acto = escritura(escenario.titular, 5, "1000", detalle_exencion="   ")
    response = await _agregar(notario, ddjj["id"], acto)
    assert response.status_code == 201, response.text
    assert response.json()["detalle_exencion"] is None
