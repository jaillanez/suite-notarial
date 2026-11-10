"""Escribanos migrados sin matrícula, fecha de juramento, CUIT o documento («a completar»)."""

import uuid
from typing import Any

import pyotp
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.padron.models import Adscripcion, Escribano, Persona, RegistroNotarial
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.padron.conftest import Factory, valid_cuit

TODOS = ["matricula_numero", "fecha_matriculacion", "cuit", "numero_documento"]
# La primera escritura llega después de la afiliación: también figura «a completar».
PRIMERA = "primera_escritura"


async def _vaciar(db_session: AsyncSession, escribano_id: str, *campos: str) -> None:
    """Deja el escribano como lo carga la migración cuando el origen no tiene esos datos."""
    eid = uuid.UUID(escribano_id)
    de_escribano = {c: None for c in campos if c in {"matricula_numero", "fecha_matriculacion"}}
    de_persona = {c: None for c in campos if c in {"cuit", "numero_documento"}}
    if de_escribano:
        await db_session.execute(update(Escribano).where(Escribano.id == eid).values(de_escribano))
    if de_persona:
        persona_id = select(Escribano.persona_id).where(Escribano.id == eid).scalar_subquery()
        await db_session.execute(update(Persona).where(Persona.id == persona_id).values(de_persona))
    await db_session.flush()
    db_session.expire_all()


def _url(item: dict[str, Any]) -> str:
    return f"/api/v1/padron/escribanos/{item['id']}"


async def test_ficha_y_listado_con_datos_a_completar(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    a = await escribano(apellido="Acompletar", nombre="Uno")
    b = await escribano(apellido="Acompletar", nombre="Dos")
    # Dos escribanos sin matrícula ni CUIT conviven (UNIQUE admite varios NULL).
    await _vaciar(db_session, a["id"], *TODOS)
    await _vaciar(db_session, b["id"], *TODOS)

    detalle = (await caja.get(_url(a))).json()
    assert detalle["a_completar"] == [*TODOS, PRIMERA]
    assert detalle["matricula_numero"] is None
    assert detalle["fecha_matriculacion"] is None
    assert detalle["cuit"] is None and detalle["persona"]["cuit"] is None
    assert detalle["persona"]["numero_documento"] is None

    listado = await caja.get("/api/v1/padron/escribanos", params={"q": "acompletar"})
    assert listado.status_code == 200
    assert {i["matricula_numero"] for i in listado.json()["items"]} == {None}
    # Una búsqueda por número no falla con matrículas vacías.
    assert (await caja.get("/api/v1/padron/escribanos", params={"q": "123"})).status_code == 200


async def test_completar_una_vez_y_auditado(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    await _vaciar(db_session, item["id"], *TODOS)
    cuit = valid_cuit()

    response = await caja.post(
        f"{_url(item)}/completar",
        json={
            "matricula_numero": 654_321,
            "fecha_matriculacion": "2001-03-01",
            "cuit": f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}",
            "numero_documento": cuit[2:10],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["a_completar"] == [PRIMERA]
    assert body["matricula_numero"] == 654_321
    assert body["fecha_matriculacion"] == "2001-03-01"
    assert body["persona"]["cuit"].replace("-", "") == cuit
    audit = (
        await db_session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "PADRON_ESCRIBANO_COMPLETADO"
            )
        )
    ).scalar_one()
    assert audit.old_value == dict.fromkeys(TODOS)
    assert audit.new_value == {
        "matricula_numero": 654_321,
        "fecha_matriculacion": "2001-03-01",
        "cuit": cuit,
        "numero_documento": cuit[2:10],
    }
    assert audit.details is not None and audit.details["escribano_id"] == item["id"]

    # Ya cargado: no se cambia por esta vía.
    again = await caja.post(f"{_url(item)}/completar", json={"matricula_numero": 654_322})
    assert again.status_code == 409


async def test_completar_solo_lo_que_falta(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    await _vaciar(db_session, item["id"], "matricula_numero")

    con_cuit = await caja.post(f"{_url(item)}/completar", json={"cuit": valid_cuit()})
    assert con_cuit.status_code == 409
    assert (await caja.post(f"{_url(item)}/completar", json={})).status_code == 422
    ok = await caja.post(f"{_url(item)}/completar", json={"matricula_numero": 777_777})
    assert ok.status_code == 200
    assert ok.json()["a_completar"] == [PRIMERA]


async def test_completar_valida_cuit_y_matricula_repetible(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    otro = await escribano()
    item = await escribano()
    await _vaciar(db_session, item["id"], "matricula_numero", "cuit")

    bueno = valid_cuit()
    malo = bueno[:10] + str((int(bueno[10]) + 1) % 10)
    invalido = await caja.post(f"{_url(item)}/completar", json={"cuit": malo})
    assert invalido.status_code == 422
    cuit_repetido = await caja.post(
        f"{_url(item)}/completar", json={"cuit": otro["persona"]["cuit"]}
    )
    assert cuit_repetido.status_code == 409
    assert "CUIT" in cuit_repetido.json()["detail"]
    # La matrícula no es única: se puede completar con una que ya tiene otro escribano.
    matricula_repetida = await caja.post(
        f"{_url(item)}/completar", json={"matricula_numero": otro["matricula_numero"]}
    )
    assert matricula_repetida.status_code == 200, matricula_repetida.text
    assert (
        await caja.post(f"{_url(item)}/completar", json={"matricula_numero": 0})
    ).status_code == 422


async def test_fecha_no_posterior_al_primer_cargo(
    caja: AsyncClient, escribano: Factory, registro: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    reg = await registro()
    cargo = await caja.post(
        f"{_url(item)}/cargos",
        json={"registro_id": reg["id"], "cargo": "TITULAR", "fecha_desde": "2018-01-01"},
    )
    assert cargo.status_code == 201, cargo.text
    # Escribano migrado con cargo y sin fecha de juramento.
    await _vaciar(db_session, item["id"], "fecha_matriculacion")

    tarde = await caja.post(f"{_url(item)}/completar", json={"fecha_matriculacion": "2019-01-01"})
    assert tarde.status_code == 422
    ok = await caja.post(f"{_url(item)}/completar", json={"fecha_matriculacion": "2016-05-01"})
    assert ok.status_code == 200


async def test_sin_fecha_de_juramento_no_se_asignan_cargos_ni_estados(
    caja: AsyncClient, escribano: Factory, registro: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    await _vaciar(db_session, item["id"], "fecha_matriculacion")
    reg = await registro()
    cargo = await caja.post(
        f"{_url(item)}/cargos",
        json={"registro_id": reg["id"], "cargo": "TITULAR", "fecha_desde": "2010-01-01"},
    )
    assert cargo.status_code == 409 and "Completar datos" in cargo.text
    estado = await caja.post(
        f"{_url(item)}/estado",
        json={"nuevo_estado": "SUSPENDIDO", "motivo": "Sumario", "fecha_efectiva": "2026-10-01"},
    )
    assert estado.status_code == 409
    # Por la edición general tampoco: un dato «a completar» va por «Completar datos».
    edicion = await caja.patch(_url(item), json={"fecha_matriculacion": "2009-05-01"})
    assert edicion.status_code == 409


async def test_completar_requiere_permiso_de_escritura(
    client: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    item = await escribano()
    await _vaciar(db_session, item["id"], "matricula_numero")
    secret = pyotp.random_base32()
    auditor = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    await login(client, auditor, secret)

    response = await client.post(f"{_url(item)}/completar", json={"matricula_numero": 1})
    assert response.status_code == 403


async def test_sin_cuit_no_se_crea_cuenta(client: AsyncClient, db_session: AsyncSession) -> None:
    secret = pyotp.random_base32()
    admin = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    await login(client, admin, secret)
    created = await client.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {
                "cuit": valid_cuit(),
                "numero_documento": "30999777",
                "apellido": "Sincuit",
                "nombre": "Cuenta",
                "email": "sin.cuit@suite-notarial.example",
            },
            "matricula_numero": 434_343,
            "fecha_matriculacion": "2015-03-01",
        },
    )
    assert created.status_code == 201, created.text
    await _vaciar(db_session, created.json()["id"], "cuit")

    response = await client.post(
        f"{_url(created.json())}/cuenta", json={"email": "sin.cuit@suite-notarial.example"}
    )
    assert response.status_code == 422
    assert "CUIT" in response.json()["detail"]


async def test_alta_manual_sigue_exigiendo_matricula_y_cuit(caja: AsyncClient) -> None:
    sin_matricula = await caja.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {
                "cuit": valid_cuit(),
                "numero_documento": "30111000",
                "apellido": "Prueba",
                "nombre": "Alta",
            },
            "fecha_matriculacion": "2015-03-01",
        },
    )
    assert sin_matricula.status_code == 422
    sin_cuit = await caja.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {"numero_documento": "30111000", "apellido": "Prueba", "nombre": "Alta"},
            "matricula_numero": 888_001,
            "fecha_matriculacion": "2015-03-01",
        },
    )
    assert sin_cuit.status_code == 422


# --------------------------------------------------------------------------- cargos y registros


async def _cargo_sin_fecha(
    caja: AsyncClient, db_session: AsyncSession, escribano_id: str, registro_id: str
) -> str:
    """Asigna un cargo y le borra la fecha desde, como lo carga la migración sin ese dato."""
    response = await caja.post(
        f"/api/v1/padron/escribanos/{escribano_id}/cargos",
        json={"registro_id": registro_id, "cargo": "TITULAR", "fecha_desde": "2020-01-01"},
    )
    assert response.status_code == 201, response.text
    cargo_id: str = response.json()["cargos"][0]["id"]
    await db_session.execute(
        update(Adscripcion).where(Adscripcion.id == uuid.UUID(cargo_id)).values(fecha_desde=None)
    )
    await db_session.flush()
    db_session.expire_all()
    return cargo_id


async def test_cargo_sin_fecha_desde_se_completa_una_vez_y_auditado(
    caja: AsyncClient, escribano: Factory, registro: Factory, db_session: AsyncSession
) -> None:
    item, reg = await escribano(), await registro()
    cargo_id = await _cargo_sin_fecha(caja, db_session, item["id"], reg["id"])

    ficha = (await caja.get(_url(item))).json()
    assert ficha["cargos"][0]["fecha_desde"] is None
    detalle = (await caja.get(f"/api/v1/padron/registros/{reg['id']}")).json()
    assert detalle["titular"]["fecha_desde"] is None

    url = f"/api/v1/padron/cargos/{cargo_id}/fecha-desde"
    # No antes del juramento (2015-03-01) ni en el futuro.
    assert (await caja.post(url, json={"fecha_desde": "2010-01-01"})).status_code == 422
    assert (await caja.post(url, json={"fecha_desde": "2999-01-01"})).status_code == 422

    response = await caja.post(url, json={"fecha_desde": "2018-07-02"})

    assert response.status_code == 200, response.text
    assert response.json()["fecha_desde"] == "2018-07-02"
    audit = (
        await db_session.execute(
            select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PADRON_CARGO_COMPLETADO")
        )
    ).scalar_one()
    assert audit.old_value is not None and audit.old_value["fecha_desde"] is None
    assert audit.new_value is not None and audit.new_value["fecha_desde"] == "2018-07-02"
    # Ya cargada: no se cambia por esta vía.
    assert (await caja.post(url, json={"fecha_desde": "2018-07-03"})).status_code == 409


async def test_cargo_cerrado_no_se_completa_despues_del_cierre_ni_pisando_otro(
    caja: AsyncClient, escribano: Factory, registro: Factory, db_session: AsyncSession
) -> None:
    item, viejo, nuevo = await escribano(), await registro(), await registro()
    cerrado = await _cargo_sin_fecha(caja, db_session, item["id"], viejo["id"])
    cierre = await caja.post(
        f"/api/v1/padron/cargos/{cerrado}/cierre",
        json={"fecha_hasta": "2021-06-30", "motivo": "Traslado de registro"},
    )
    assert cierre.status_code == 200, cierre.text
    vigente = await caja.post(
        f"/api/v1/padron/escribanos/{item['id']}/cargos",
        json={"registro_id": nuevo["id"], "cargo": "ADSCRIPTO", "fecha_desde": "2021-07-01"},
    )
    assert vigente.status_code == 201, vigente.text
    vigente_id = next(c["id"] for c in vigente.json()["cargos"] if c["is_current"])
    await db_session.execute(
        update(Adscripcion).where(Adscripcion.id == uuid.UUID(vigente_id)).values(fecha_desde=None)
    )
    await db_session.flush()
    db_session.expire_all()

    url = f"/api/v1/padron/cargos/{cerrado}/fecha-desde"
    assert (await caja.post(url, json={"fecha_desde": "2021-07-01"})).status_code == 422
    assert (await caja.post(url, json={"fecha_desde": "2016-01-01"})).status_code == 200
    # El vigente no puede empezar antes del cierre del anterior.
    url_vigente = f"/api/v1/padron/cargos/{vigente_id}/fecha-desde"
    choque = await caja.post(url_vigente, json={"fecha_desde": "2021-06-01"})
    assert choque.status_code == 422
    assert "Registro" in choque.json()["detail"]
    assert (await caja.post(url_vigente, json={"fecha_desde": "2021-07-01"})).status_code == 200


async def test_completar_fecha_desde_requiere_permiso_de_escritura(
    client: AsyncClient,
    caja: AsyncClient,
    escribano: Factory,
    registro: Factory,
    db_session: AsyncSession,
) -> None:
    item, reg = await escribano(), await registro()
    cargo_id = await _cargo_sin_fecha(caja, db_session, item["id"], reg["id"])
    secret = pyotp.random_base32()
    auditor = await make_user(db_session, roles=("ROLE_AUDITOR",), totp_secret=secret)
    await login(client, auditor, secret)

    response = await client.post(
        f"/api/v1/padron/cargos/{cargo_id}/fecha-desde", json={"fecha_desde": "2018-07-02"}
    )
    assert response.status_code == 403


async def test_registro_sin_departamento_se_muestra_y_se_completa_editando(
    caja: AsyncClient, registro: Factory, db_session: AsyncSession
) -> None:
    reg = await registro()
    await db_session.execute(
        update(RegistroNotarial)
        .where(RegistroNotarial.id == uuid.UUID(reg["id"]))
        .values(departamento=None)
    )
    await db_session.flush()
    db_session.expire_all()
    url = f"/api/v1/padron/registros/{reg['id']}"

    assert (await caja.get(url)).json()["departamento"] is None
    listado = await caja.get("/api/v1/padron/registros", params={"q": str(reg["numero_registro"])})
    assert listado.status_code == 200
    assert listado.json()["items"][0]["departamento"] is None

    response = await caja.patch(url, json={"departamento": "Rivadavia"})
    assert response.status_code == 200, response.text
    assert response.json()["departamento"] == "Rivadavia"
