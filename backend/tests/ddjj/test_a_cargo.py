"""Escribano a cargo: designación con fecha desde y hasta, aprobación opcional de la Caja.

El designado conserva su propio cargo (es titular de otro registro) y, solo entre las fechas
de la designación aprobada, opera las DDJJ del registro y figura en ellas como «a cargo».
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import User
from app.modules.padron import router_a_cargo
from app.modules.padron.models import Adscripcion, Escribano
from tests.ddjj.conftest import HOY, Escenario, _client, _escribano, escritura
from tests.ddjj.test_protocolo import _agregar, _borrador
from tests.iam.factories import make_user
from tests.iam.test_rbac import login


@pytest.fixture(autouse=True)
def hoy_a_cargo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_a_cargo, "today_local", lambda: HOY)


@dataclass
class Designado:
    escribano: Escribano
    user: User


@pytest.fixture
async def designado(db_session: AsyncSession, escenario: Escenario) -> Designado:
    """Titular del otro registro (otro departamento): puede quedar a cargo del primero."""
    user = await make_user(db_session)
    escribano = await _escribano(db_session, "Designado", user)
    db_session.add(
        Adscripcion(
            escribano_id=escribano.id,
            registro_id=escenario.otro_registro.id,
            cargo="TITULAR",
            fecha_desde=date(2018, 1, 1),
        )
    )
    await db_session.commit()
    return Designado(escribano, user)


@pytest.fixture
async def a_cargo_client(app: FastAPI, designado: Designado) -> AsyncIterator[AsyncClient]:
    async with await _client(app) as ac:
        await login(ac, designado.user)
        yield ac


def _designacion(
    e: Escenario, d: Designado, desde: str = "2026-10-01", hasta: str = "2026-10-31"
) -> dict[str, Any]:
    return {
        "registro_id": str(e.registro.id),
        "escribano_id": str(d.escribano.id),
        "fecha_desde": desde,
        "fecha_hasta": hasta,
        "motivo": "Licencia del titular",
    }


async def _designar(client: AsyncClient, body: dict[str, Any]) -> Any:
    return await client.post("/api/v1/a-cargo", json=body)


async def _registros_operables(client: AsyncClient) -> set[str]:
    response = await client.get("/api/v1/ddjj/registros")
    assert response.status_code == 200, response.text
    return {r["id"] for r in response.json()}


async def test_por_aviso_rige_al_cargarla_y_habilita_solo_entre_fechas(
    notario: AsyncClient,
    a_cargo_client: AsyncClient,
    escenario: Escenario,
    designado: Designado,
) -> None:
    creada = await _designar(
        notario, _designacion(escenario, designado, "2026-10-05", "2026-10-31")
    )
    assert creada.status_code == 201, creada.text
    body = creada.json()
    assert body["estado"] == "APROBADA"
    assert body["rige_hoy"] is True
    # Un escribano no ve quién de la Caja operó.
    assert body["cargada_por"] is None

    # Conserva su registro y suma el que tiene a cargo.
    operables = await _registros_operables(a_cargo_client)
    assert operables == {str(escenario.registro.id), str(escenario.otro_registro.id)}

    ddjj = await _borrador(a_cargo_client, escenario, "2026-10")
    dentro = escritura(designado.escribano, 10, "1000", fecha_acto="2026-10-06")
    respuesta = await _agregar(a_cargo_client, ddjj["id"], dentro)
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["cargo"] == "SUPLENTE_INTERINO"
    antes = escritura(designado.escribano, 11, "1000", fecha_acto="2026-10-02")
    assert (await _agregar(a_cargo_client, ddjj["id"], antes)).status_code == 422

    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    equipo = {e["apellido_nombre"].split(",")[0]: e["cargo"] for e in detalle["escribanos"]}
    assert equipo == {
        "Titular": "TITULAR",
        "Adscripto": "ADSCRIPTO",
        "Designado": "SUPLENTE_INTERINO",
    }
    # Quien está a cargo no paga aporte médico por este registro.
    liq = (
        await notario.get(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion",
            params={"fecha_pago": "2026-10-23"},
        )
    ).json()
    assert liq["cantidad_aportes_medicos"] == 2


async def test_fuera_de_las_fechas_no_opera(
    notario: AsyncClient,
    a_cargo_client: AsyncClient,
    escenario: Escenario,
    designado: Designado,
) -> None:
    futura = await _designar(
        notario, _designacion(escenario, designado, "2026-11-01", "2026-11-30")
    )
    assert futura.status_code == 201, futura.text
    assert futura.json()["rige_hoy"] is False
    assert str(escenario.registro.id) not in await _registros_operables(a_cargo_client)
    nueva = await a_cargo_client.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.registro.id), "periodo": "2026-10"},
    )
    assert nueva.status_code == 403


async def test_con_aprobacion_espera_a_la_caja(
    notario: AsyncClient,
    staff: AsyncClient,
    a_cargo_client: AsyncClient,
    escenario: Escenario,
    designado: Designado,
    db_session: AsyncSession,
) -> None:
    # Solo la Caja cambia el ajuste.
    assert (
        await notario.put("/api/v1/a-cargo/ajustes", json={"a_cargo_requiere_aprobacion": True})
    ).status_code == 403
    ajuste = await staff.put("/api/v1/a-cargo/ajustes", json={"a_cargo_requiere_aprobacion": True})
    assert ajuste.status_code == 200, ajuste.text
    assert (await notario.get("/api/v1/a-cargo/ajustes")).json()["a_cargo_requiere_aprobacion"]

    creada = (await _designar(notario, _designacion(escenario, designado))).json()
    assert creada["estado"] == "PENDIENTE"
    assert creada["puede_aprobar"] is False
    assert str(escenario.registro.id) not in await _registros_operables(a_cargo_client)

    # El escribano no aprueba; la Caja sí.
    assert (await notario.post(f"/api/v1/a-cargo/{creada['id']}/aprobar")).status_code == 403
    pendientes = (await staff.get("/api/v1/a-cargo", params={"estado": "PENDIENTE"})).json()
    assert [d["id"] for d in pendientes["items"]] == [creada["id"]]
    assert pendientes["items"][0]["puede_aprobar"] is True
    aprobada = await staff.post(f"/api/v1/a-cargo/{creada['id']}/aprobar")
    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["estado"] == "APROBADA"
    assert aprobada.json()["resuelta_por"] is not None
    assert str(escenario.registro.id) in await _registros_operables(a_cargo_client)
    # Ya resuelta, no se vuelve a aprobar ni se rechaza.
    assert (await staff.post(f"/api/v1/a-cargo/{creada['id']}/aprobar")).status_code == 409

    eventos = (
        await db_session.scalars(
            select(AuditSecurityLog.event_type).where(AuditSecurityLog.event_type.like("PADRON_A%"))
        )
    ).all()
    assert {
        "PADRON_AJUSTES_CAMBIADOS",
        "PADRON_A_CARGO_DESIGNADO",
        "PADRON_A_CARGO_APROBADO",
    } <= set(eventos)


async def test_rechazo_con_motivo(
    notario: AsyncClient, staff: AsyncClient, escenario: Escenario, designado: Designado
) -> None:
    await staff.put("/api/v1/a-cargo/ajustes", json={"a_cargo_requiere_aprobacion": True})
    creada = (await _designar(notario, _designacion(escenario, designado))).json()
    sin_motivo = await staff.post(f"/api/v1/a-cargo/{creada['id']}/rechazar", json={"motivo": ""})
    assert sin_motivo.status_code == 422
    rechazada = await staff.post(
        f"/api/v1/a-cargo/{creada['id']}/rechazar", json={"motivo": "Falta la nota del titular"}
    )
    assert rechazada.status_code == 200, rechazada.text
    assert rechazada.json()["estado"] == "RECHAZADA"
    # Rechazada, el registro queda libre para otra designación en esas fechas.
    otra = await _designar(notario, _designacion(escenario, designado))
    assert otra.status_code == 201, otra.text


async def test_la_que_carga_la_caja_rige_siempre(
    staff: AsyncClient, escenario: Escenario, designado: Designado
) -> None:
    await staff.put("/api/v1/a-cargo/ajustes", json={"a_cargo_requiere_aprobacion": True})
    creada = await _designar(staff, _designacion(escenario, designado))
    assert creada.status_code == 201, creada.text
    assert creada.json()["estado"] == "APROBADA"
    assert creada.json()["cargada_por"] is not None


async def test_validaciones(
    notario: AsyncClient,
    a_cargo_client: AsyncClient,
    escenario: Escenario,
    designado: Designado,
) -> None:
    # El titular no queda a cargo de su propio registro.
    propio = _designacion(escenario, designado) | {"escribano_id": str(escenario.titular.id)}
    assert (await _designar(notario, propio)).status_code == 422
    # Fechas al revés.
    reves = _designacion(escenario, designado, "2026-10-20", "2026-10-10")
    assert (await _designar(notario, reves)).status_code == 422
    # Solo el titular del registro (o la Caja) designa: el designado no se designa solo.
    assert (await _designar(a_cargo_client, _designacion(escenario, designado))).status_code == 403

    assert (await _designar(notario, _designacion(escenario, designado))).status_code == 201
    superpuesta = await _designar(
        notario, _designacion(escenario, designado, "2026-10-31", "2026-11-15")
    )
    assert superpuesta.status_code == 409
    assert "ya tiene a cargo" in superpuesta.json()["detail"]
    contigua = await _designar(
        notario, _designacion(escenario, designado, "2026-11-01", "2026-11-15")
    )
    assert contigua.status_code == 201, contigua.text


async def test_anular_y_terminar_respetan_los_actos_declarados(
    notario: AsyncClient,
    a_cargo_client: AsyncClient,
    escenario: Escenario,
    designado: Designado,
    db_session: AsyncSession,
) -> None:
    creada = (await _designar(notario, _designacion(escenario, designado))).json()
    ddjj = await _borrador(a_cargo_client, escenario, "2026-10")
    acto = escritura(designado.escribano, 20, "1000", fecha_acto="2026-10-15")
    assert (await _agregar(a_cargo_client, ddjj["id"], acto)).status_code == 201

    motivo = {"motivo": "Volvió el titular"}
    assert (
        await notario.post(f"/api/v1/a-cargo/{creada['id']}/anular", json=motivo)
    ).status_code == 409
    antes_del_acto = await notario.post(
        f"/api/v1/a-cargo/{creada['id']}/terminar", json={"fecha_hasta": "2026-10-10", **motivo}
    )
    assert antes_del_acto.status_code == 409
    terminada = await notario.post(
        f"/api/v1/a-cargo/{creada['id']}/terminar", json={"fecha_hasta": "2026-10-15", **motivo}
    )
    assert terminada.status_code == 200, terminada.text
    assert terminada.json()["fecha_hasta"] == "2026-10-15"
    assert terminada.json()["rige_hoy"] is False
    assert str(escenario.registro.id) not in await _registros_operables(a_cargo_client)

    # Sin borrado físico (INM).
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("DELETE FROM padron_designaciones_a_cargo"))


async def test_anular_una_que_no_respalda_actos(
    notario: AsyncClient, escenario: Escenario, designado: Designado
) -> None:
    creada = (await _designar(notario, _designacion(escenario, designado))).json()
    anulada = await notario.post(
        f"/api/v1/a-cargo/{creada['id']}/anular", json={"motivo": "Se cargó por error"}
    )
    assert anulada.status_code == 200, anulada.text
    assert anulada.json()["estado"] == "ANULADA"
    assert anulada.json()["puede_anular"] is False


async def test_visibilidad(
    app: FastAPI,
    notario: AsyncClient,
    a_cargo_client: AsyncClient,
    escenario: Escenario,
    designado: Designado,
    db_session: AsyncSession,
) -> None:
    creada = (await _designar(notario, _designacion(escenario, designado))).json()
    # El designado la ve; un escribano ajeno, no (ni sabe que existe).
    assert (await a_cargo_client.get(f"/api/v1/a-cargo/{creada['id']}")).status_code == 200
    ajeno = await make_user(db_session)
    await _escribano(db_session, "Ajeno", ajeno)
    await db_session.commit()
    async with await _client(app) as otro:
        await login(otro, ajeno)
        assert (await otro.get(f"/api/v1/a-cargo/{creada['id']}")).status_code == 404
        assert (await otro.get("/api/v1/a-cargo")).json()["total"] == 0


async def test_elegibles_y_registros(
    notario: AsyncClient, staff: AsyncClient, escenario: Escenario, designado: Designado
) -> None:
    encontrados = (await notario.get("/api/v1/a-cargo/elegibles", params={"q": "Designado"})).json()
    assert [e["id"] for e in encontrados] == [str(designado.escribano.id)]
    assert encontrados[0]["numero_registro"] == escenario.otro_registro.numero_registro
    por_matricula = (
        await notario.get(
            "/api/v1/a-cargo/elegibles", params={"q": str(designado.escribano.matricula_numero)}
        )
    ).json()
    assert [e["id"] for e in por_matricula] == [str(designado.escribano.id)]
    # El titular solo designa en su registro; la Caja, en cualquiera.
    propios = (await notario.get("/api/v1/a-cargo/registros")).json()
    assert [r["id"] for r in propios] == [str(escenario.registro.id)]
    todos = {r["id"] for r in (await staff.get("/api/v1/a-cargo/registros")).json()}
    assert {str(escenario.registro.id), str(escenario.otro_registro.id)} <= todos


async def test_el_padron_ya_no_asigna_a_cargo_sin_fechas(
    staff: AsyncClient, escenario: Escenario, designado: Designado
) -> None:
    response = await staff.post(
        f"/api/v1/padron/escribanos/{designado.escribano.id}/cargos",
        json={
            "registro_id": str(escenario.registro.id),
            "cargo": "SUPLENTE_INTERINO",
            "fecha_desde": "2026-10-01",
        },
    )
    assert response.status_code == 422
    assert "designación" in response.json()["detail"]


async def test_buscar_elegibles_solo_quien_designa(
    app: FastAPI, escenario: Escenario, db_session: AsyncSession
) -> None:
    sin_registro = await make_user(db_session)
    await _escribano(db_session, "SinRegistro", sin_registro)
    await db_session.commit()
    async with await _client(app) as cliente:
        await login(cliente, sin_registro)
        respuesta = await cliente.get("/api/v1/a-cargo/elegibles", params={"q": "Titular"})
        assert respuesta.status_code == 403


async def test_el_titular_no_designa_antes_de_su_propio_cargo(
    notario: AsyncClient, staff: AsyncClient, escenario: Escenario, designado: Designado
) -> None:
    # El titular del escenario lo es desde el 01/01/2020.
    previa = _designacion(escenario, designado, "2019-12-01", "2020-01-31")
    respuesta = await _designar(notario, previa)
    assert respuesta.status_code == 422
    assert "antes de tu cargo de titular" in respuesta.json()["detail"]
    # La Caja sí puede registrar una designación histórica.
    assert (await _designar(staff, previa)).status_code == 201


async def test_cerrar_al_titular_termina_sus_designaciones(
    notario: AsyncClient,
    staff: AsyncClient,
    escenario: Escenario,
    designado: Designado,
    db_session: AsyncSession,
) -> None:
    vigente = (await _designar(notario, _designacion(escenario, designado))).json()
    futura = (
        await _designar(notario, _designacion(escenario, designado, "2026-11-01", "2026-11-30"))
    ).json()
    cargo_id = await db_session.scalar(
        select(Adscripcion.id).where(
            Adscripcion.escribano_id == escenario.titular.id, Adscripcion.is_current.is_(True)
        )
    )
    cierre = await staff.post(
        f"/api/v1/padron/cargos/{cargo_id}/cierre",
        json={"fecha_hasta": "2026-10-20", "motivo": "Renuncia del titular"},
    )
    assert cierre.status_code == 200, cierre.text

    terminada = (await staff.get(f"/api/v1/a-cargo/{vigente['id']}")).json()
    assert terminada["estado"] == "APROBADA"
    assert terminada["fecha_hasta"] == "2026-10-20"
    anulada = (await staff.get(f"/api/v1/a-cargo/{futura['id']}")).json()
    assert anulada["estado"] == "ANULADA"
    assert "cargo del titular" in anulada["motivo_resolucion"]
