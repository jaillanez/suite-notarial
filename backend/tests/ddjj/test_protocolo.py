"""Controles del libro de protocolo: numeración anual, folios, fechas y números salteados."""

import uuid
from dataclasses import replace
from datetime import date
from typing import Any

from httpx import AsyncClient

from app.modules.ddjj import protocolo
from app.modules.ddjj.protocolo import ActoDeclarado, Candidato, NivelControl
from tests.ddjj.conftest import Escenario, escritura

SETIEMBRE = uuid.uuid4()  # DDJJ de los actos declarados


def _acto(
    numero: int, folio: int | None, dia: int, tipo: str = "GENERAL", ddjj: uuid.UUID = SETIEMBRE
) -> ActoDeclarado:
    return ActoDeclarado(uuid.uuid4(), ddjj, tipo, numero, folio, date(2026, 9, dia), "2026-09")


DECLARADOS = [_acto(10, 20, 3), _acto(11, 22, 5), _acto(12, 25, 9), _acto(15, 31, 20)]
VISTA = protocolo.Vista.total(DECLARADOS)


def _codigos(c: Candidato) -> dict[str, NivelControl]:
    return {x.codigo: x.nivel for x in protocolo.revisar(VISTA, c)}


def test_numero_repetido_bloquea() -> None:
    controles = protocolo.revisar(VISTA, Candidato("GENERAL", 11, 22, date(2026, 9, 5)))
    assert [c.codigo for c in controles] == ["NUMERO_REPETIDO"]
    assert controles[0].nivel is NivelControl.BLOQUEANTE
    assert "DDJJ 09/2026" in controles[0].mensaje
    # El mismo número en el otro protocolo no choca.
    assert _codigos(Candidato("AUXILIAR", 11, 22, date(2026, 9, 5))) == {}


def test_acto_multiple_solo_en_la_misma_declaracion() -> None:
    misma = Candidato("GENERAL", 11, 22, date(2026, 9, 5), ddjj_id=SETIEMBRE)
    controles = protocolo.revisar(VISTA, misma)
    assert [c.codigo for c in controles] == ["NUMERO_REPETIDO"]
    assert "marcalo como acto múltiple" in controles[0].mensaje
    # Otro acto de la misma escritura: se admite y no se avisa nada del folio compartido.
    assert protocolo.revisar(VISTA, replace(misma, multiple=True)) == []
    # En otra DDJJ del año sigue bloqueando aunque se marque como múltiple.
    otra = replace(misma, ddjj_id=uuid.uuid4(), multiple=True)
    assert _codigos(otra) == {"NUMERO_REPETIDO": NivelControl.BLOQUEANTE}


def test_folio_compartido_con_la_contigua_es_normal() -> None:
    # La 13 empieza en el folio donde terminó la 12.
    assert _codigos(Candidato("GENERAL", 13, 25, date(2026, 9, 10))) == {}
    # Pero el folio de la 10 en la 13 no corresponde.
    assert _codigos(Candidato("GENERAL", 13, 20, date(2026, 9, 10))) == {
        "FOLIO_REPETIDO": NivelControl.ADVERTENCIA,
        "FOLIO_FUERA_DE_ORDEN": NivelControl.ADVERTENCIA,
    }


def test_folio_y_fecha_fuera_de_orden() -> None:
    codigos = _codigos(Candidato("GENERAL", 13, 40, date(2026, 9, 2)))
    assert codigos == {
        "FOLIO_FUERA_DE_ORDEN": NivelControl.ADVERTENCIA,
        "FECHA_FUERA_DE_ORDEN": NivelControl.ADVERTENCIA,
    }
    # En orden: sin controles.
    assert _codigos(Candidato("GENERAL", 13, 27, date(2026, 9, 12))) == {}


def test_al_revisar_un_acto_cargado_se_excluye_a_si_mismo() -> None:
    propio = DECLARADOS[1]
    c = Candidato("GENERAL", propio.numero, propio.folio, propio.fecha, excluir=propio.id)
    assert protocolo.revisar(VISTA, c) == []


def test_huecos() -> None:
    huecos = protocolo.huecos(protocolo.Vista.total([*DECLARADOS, _acto(1, 1, 1, "AUXILIAR")]))
    assert huecos == [protocolo.Hueco("GENERAL", ((13, 14),), 2)]
    # Un salto largo es un solo tramo, no 198 números sueltos.
    largos = protocolo.huecos(
        protocolo.Vista.total([_acto(1, None, 1), _acto(200, None, 2), _acto(202, None, 3)])
    )
    assert largos == [protocolo.Hueco("GENERAL", ((2, 199), (201, 201)), 199)]


def test_sin_alcance_no_se_citan_datos_de_otras_escrituras() -> None:
    """Fuera del alcance: el número repetido bloquea sin decir dónde, y los avisos de folio y
    fecha no se calculan (su sola presencia revelaría datos de DDJJ ajenas)."""
    vista = protocolo.Vista(DECLARADOS, lambda _periodo: False)
    controles = protocolo.revisar(vista, Candidato("GENERAL", 11, 40, date(2026, 9, 1)))
    assert [(x.codigo, x.mensaje) for x in controles] == [
        (
            "NUMERO_REPETIDO",
            "La escritura N° 11 del protocolo general ya está declarada en otra DDJJ del año.",
        )
    ]
    assert protocolo.huecos(vista) == []


def test_indice_con_muchos_actos() -> None:
    """El índice resuelve cada control sin recorrer el año (miles de escrituras)."""
    muchos = [_acto(n, n, 1 + n % 28) for n in range(1, 5001)]
    vista = protocolo.Vista.total(muchos)
    assert protocolo.revisar(vista, Candidato("GENERAL", 5001, 5001, date(2026, 9, 28))) == []
    assert [x.codigo for x in protocolo.revisar(vista, Candidato("GENERAL", 5002, 3, None))] == [
        "FOLIO_REPETIDO",
        "FOLIO_FUERA_DE_ORDEN",
    ]


# --------------------------------------------------------------------------- API


async def _borrador(client: AsyncClient, e: Escenario, periodo: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/ddjj/declaraciones", json={"registro_id": str(e.registro.id), "periodo": periodo}
    )
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


async def _agregar(client: AsyncClient, ddjj_id: str, acto: dict[str, Any]) -> Any:
    return await client.post(f"/api/v1/ddjj/declaraciones/{ddjj_id}/actos", json=acto)


async def test_numero_repetido_en_otro_mes_bloquea(
    notario: AsyncClient, escenario: Escenario
) -> None:
    agosto = await _borrador(notario, escenario, "2026-08")
    setiembre = await _borrador(notario, escenario, "2026-09")
    primero = await _agregar(
        notario, agosto["id"], escritura(escenario.titular, 50, "1000", fecha_acto="2026-08-20")
    )
    assert primero.status_code == 201, primero.text

    repetido = await _agregar(notario, setiembre["id"], escritura(escenario.titular, 50, "1000"))
    assert repetido.status_code == 409
    assert "ya está declarada en la DDJJ 08/2026" in repetido.json()["detail"]
    # En el protocolo auxiliar el 50 está libre.
    auxiliar = await _agregar(
        notario,
        setiembre["id"],
        escritura(escenario.titular, 50, "1000", tipo_protocolo="AUXILIAR"),
    )
    assert auxiliar.status_code == 201, auxiliar.text


async def test_verificacion_en_vivo(notario: AsyncClient, escenario: Escenario) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    await _agregar(notario, ddjj["id"], escritura(escenario.titular, 10, "1000", folio=20))
    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos/verificacion"

    # Datos parciales: alcanza para el aporte.
    parcial = await notario.post(
        url, json={"categoria": "ESCRITURA_CON_VALOR", "base_imponible": "1000000"}
    )
    assert parcial.status_code == 200, parcial.text
    assert parcial.json()["aporte"] is not None
    assert parcial.json()["controles"] == []

    repetido = (
        await notario.post(url, json={"numero_escritura": 10, "fecha_acto": "2026-09-15"})
    ).json()
    assert [c["codigo"] for c in repetido["controles"]] == ["NUMERO_REPETIDO"]
    assert repetido["controles"][0]["nivel"] == "BLOQUEANTE"
    assert repetido["aporte"] is None  # sin categoría todavía

    desordenado = (
        await notario.post(
            url, json={"numero_escritura": 11, "folio": 5, "fecha_acto": "2026-09-14"}
        )
    ).json()
    assert {c["codigo"] for c in desordenado["controles"]} == {
        "FOLIO_FUERA_DE_ORDEN",
        "FECHA_FUERA_DE_ORDEN",
    }


async def test_ficha_con_controles_y_numeros_salteados(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    for numero, folio, dia in ((20, 40, "10"), (23, 30, "12"), (24, 45, "16")):
        response = await _agregar(
            notario,
            ddjj["id"],
            escritura(escenario.titular, numero, "1000", folio=folio, fecha_acto=f"2026-09-{dia}"),
        )
        assert response.status_code == 201, response.text

    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert detalle["huecos"] == [
        {"tipo_protocolo": "GENERAL", "tramos": [{"desde": 21, "hasta": 22}], "total": 2}
    ]
    por_numero = {a["numero_escritura"]: a["id"] for a in detalle["actos"]}
    # La 23 está en el folio 30, antes que el 40 de la 20.
    assert [c["codigo"] for c in detalle["controles"][por_numero[23]]] == ["FOLIO_FUERA_DE_ORDEN"]
    # La 24 está en orden: sin controles.
    assert por_numero[24] not in detalle["controles"]


async def test_la_rectificativa_no_choca_con_la_rectificada(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    await _agregar(notario, ddjj["id"], escritura(escenario.titular, 70, "1000"))
    presentada = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    assert presentada.status_code == 201, presentada.text
    rect = (await notario.post(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/rectificar")).json()
    # La escritura 70 vive ahora en la rectificativa: no figura repetida.
    assert rect["controles"] == {}
    nueva = await _agregar(notario, rect["id"], escritura(escenario.titular, 71, "1000"))
    assert nueva.status_code == 201, nueva.text


async def test_la_verificacion_exige_poder_operar_el_registro(
    client: AsyncClient, notario: AsyncClient, escenario: Escenario, db_session: Any
) -> None:
    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    ddjj = await _borrador(notario, escenario, "2026-09")
    await login(client, await make_user(db_session))  # escribano sin cargo en el registro
    response = await client.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos/verificacion",
        json={"numero_escritura": 1},
    )
    assert response.status_code in (403, 404)


async def test_al_presentar_se_controla_otra_vez_la_numeracion(
    notario: AsyncClient, escenario: Escenario, db_session: Any
) -> None:
    """Si un número repetido llegara a la base por otra vía, la DDJJ no se presenta."""
    from sqlalchemy import update

    from app.modules.ddjj.models import Acto

    agosto = await _borrador(notario, escenario, "2026-08")
    setiembre = await _borrador(notario, escenario, "2026-09")
    a = await _agregar(
        notario, agosto["id"], escritura(escenario.titular, 80, "1000", fecha_acto="2026-08-20")
    )
    b = await _agregar(notario, setiembre["id"], escritura(escenario.titular, 81, "1000"))
    assert a.status_code == b.status_code == 201
    await db_session.execute(
        update(Acto).where(Acto.id == uuid.UUID(b.json()["id"])).values(numero_escritura=80)
    )
    await db_session.flush()
    response = await notario.post(
        f"/api/v1/ddjj/declaraciones/{setiembre['id']}/presentar",
        json={"fecha_pago": "2026-10-23"},
    )
    assert response.status_code == 409
    assert "No se puede presentar" in response.json()["detail"]


async def test_aporte_multiple_en_la_misma_escritura(
    notario: AsyncClient, escenario: Escenario
) -> None:
    """Varios actos de una escritura van en la misma DDJJ, cada uno con su aporte."""
    ddjj = await _borrador(notario, escenario, "2026-09")
    agosto = await _borrador(notario, escenario, "2026-08")
    primero = await _agregar(notario, ddjj["id"], escritura(escenario.titular, 48, "1000", folio=9))
    assert primero.status_code == 201, primero.text
    assert primero.json()["orden_en_escritura"] == 1

    sin_marcar = await _agregar(notario, ddjj["id"], escritura(escenario.titular, 48, "500"))
    assert sin_marcar.status_code == 409
    assert "acto múltiple" in sin_marcar.json()["detail"]

    hipoteca = escritura(
        escenario.titular, 48, "500", folio=9, naturaleza="Hipoteca", acto_multiple=True
    )
    segundo = await _agregar(notario, ddjj["id"], hipoteca)
    assert segundo.status_code == 201, segundo.text
    assert segundo.json()["orden_en_escritura"] == 2
    tercero = await _agregar(notario, ddjj["id"], hipoteca)
    assert tercero.json()["orden_en_escritura"] == 3

    # La escritura tiene una sola fecha.
    otra_fecha = await _agregar(notario, ddjj["id"], {**hipoteca, "fecha_acto": "2026-09-16"})
    assert otra_fecha.status_code == 422
    # Un acto múltiple necesita su primer acto en la misma DDJJ.
    suelto = await _agregar(notario, ddjj["id"], {**hipoteca, "numero_escritura": 49})
    assert suelto.status_code == 422
    assert "cargá primero su primer acto" in suelto.json()["detail"]
    # Y no se puede repartir la escritura en otra DDJJ.
    en_agosto = await _agregar(notario, agosto["id"], {**hipoteca, "fecha_acto": "2026-08-20"})
    assert en_agosto.status_code == 409

    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert detalle["controles"] == {}  # los hermanos de escritura no son repetidos
    assert sorted(a["orden_en_escritura"] for a in detalle["actos"]) == [1, 2, 3]

    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos/verificacion"
    vivo = (await notario.post(url, json={"numero_escritura": 48, "acto_multiple": True})).json()
    assert vivo["controles"] == []

    presentada = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    assert presentada.status_code == 201, presentada.text
    rect = (await notario.post(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/rectificar")).json()
    assert sorted(a["orden_en_escritura"] for a in rect["actos"]) == [1, 2, 3]
