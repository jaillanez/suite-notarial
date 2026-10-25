"""Quién ve y quién opera cada DDJJ; inmutabilidad en la base."""

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ddjj.conftest import Escenario, escritura
from tests.iam.factories import make_user
from tests.iam.test_rbac import login


async def _presentada(notario: AsyncClient, e: Escenario) -> tuple[str, str]:
    ddjj = (
        await notario.post(
            "/api/v1/ddjj/declaraciones",
            json={"registro_id": str(e.registro.id), "periodo": "2026-09"},
        )
    ).json()
    await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos",
        json=escritura(e.titular, 1, "1000000.00"),
    )
    boleta = (
        await notario.post(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar",
            json={"fecha_pago": "2026-10-23"},
        )
    ).json()
    return ddjj["id"], boleta["id"]


async def test_escribano_solo_opera_su_registro(notario: AsyncClient, escenario: Escenario) -> None:
    registros = (await notario.get("/api/v1/ddjj/registros")).json()
    ajeno = await notario.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.otro_registro.id), "periodo": "2026-09"},
    )

    assert [r["id"] for r in registros] == [str(escenario.registro.id)]
    assert {e["cargo"] for e in registros[0]["escribanos"]} == {"TITULAR", "ADSCRIPTO"}
    assert ajeno.status_code == 403


async def test_ddjj_y_boletas_ajenas_no_se_ven(
    notario: AsyncClient, client: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    ddjj_id, boleta_id = await _presentada(notario, escenario)
    otro = await make_user(db_session)
    await login(client, otro)  # escribano sin cargo en el registro

    assert (await client.get(f"/api/v1/ddjj/declaraciones/{ddjj_id}")).status_code == 404
    assert (await client.get(f"/api/v1/ddjj/boletas/{boleta_id}")).status_code == 404
    assert (await client.get(f"/api/v1/ddjj/boletas/{boleta_id}/pdf")).status_code == 404
    listado = (await client.get("/api/v1/ddjj/declaraciones")).json()
    assert listado["total"] == 0


async def test_la_caja_consulta_y_carga_cualquier_registro(
    notario: AsyncClient, staff: AsyncClient, escenario: Escenario
) -> None:
    ddjj_id, _ = await _presentada(notario, escenario)

    listado = (await staff.get("/api/v1/ddjj/declaraciones", params={"periodo": "2026-09"})).json()
    ajeno = await staff.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.otro_registro.id), "periodo": "2026-09"},
    )

    assert ddjj_id in [d["id"] for d in listado["items"]]
    assert ajeno.status_code == 201
    assert ajeno.json()["puede_operar"] is True


async def test_tesoreria_lee_pero_no_carga(
    client: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_TESORERIA",), totp_secret=secret)
    await login(client, user, secret)

    response = await client.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.registro.id), "periodo": "2026-09"},
    )

    assert response.status_code == 403


async def test_vencimientos(
    staff: AsyncClient,
    client: AsyncClient,
    notario: AsyncClient,
    escenario: Escenario,
    db_session: AsyncSession,
) -> None:
    await _presentada(notario, escenario)
    secret = pyotp.random_base32()
    admin = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    await login(client, admin, secret)

    listado = (await notario.get("/api/v1/ddjj/vencimientos", params={"anio": 2026})).json()
    caja = await staff.put(
        "/api/v1/ddjj/vencimientos/2026-11", json={"fecha_vencimiento": "2026-12-28"}
    )
    nuevo = await client.put(
        "/api/v1/ddjj/vencimientos/2026-11", json={"fecha_vencimiento": "2026-12-28"}
    )
    anterior_al_fin = await client.put(
        "/api/v1/ddjj/vencimientos/2026-12", json={"fecha_vencimiento": "2026-12-20"}
    )
    con_boletas = await client.put(
        "/api/v1/ddjj/vencimientos/2026-09", json={"fecha_vencimiento": "2026-10-30"}
    )

    assert len(listado) == len({v["periodo"] for v in listado}) >= 10
    assert caja.status_code == 403
    assert nuevo.status_code == 200
    assert anterior_al_fin.status_code == 422
    assert con_boletas.status_code == 409


async def test_verificacion_de_codigo_inexistente_o_invalido(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/boletas/verificar/AAAAAAAAAAAAAAAA")).status_code == 404
    assert (await client.get("/api/v1/boletas/verificar/no-es-un-codigo")).status_code == 422


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ddjj_boletas SET total_a_pagar = total_a_pagar + 1",
        "UPDATE ddjj_actos SET base_imponible = base_imponible + 1",
        "UPDATE ddjj_declaraciones SET observaciones = 'x' WHERE estado = 'PRESENTADA'",
        "UPDATE ddjj_vencimientos SET fecha_vencimiento = fecha_vencimiento + 1 "
        "WHERE periodo = '2026-09'",
        "INSERT INTO ddjj_actos (id, ddjj_id, escribano_id, cargo, tipo_protocolo, "
        "numero_escritura, fecha_acto, naturaleza, categoria, base_imponible) "
        "SELECT gen_random_uuid(), a.ddjj_id, a.escribano_id, a.cargo, a.tipo_protocolo, 999, "
        "a.fecha_acto, 'x', 'OTRO_ACTO', 0 FROM ddjj_actos a",
        "DELETE FROM ddjj_boletas",
        "DELETE FROM ddjj_declaraciones",
        "TRUNCATE ddjj_actos CASCADE",
    ],
)
async def test_lo_presentado_es_inmutable_en_la_base(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession, statement: str
) -> None:
    await _presentada(notario, escenario)

    with pytest.raises(
        DBAPIError,
        match=r"no se modifica|no está en borrador|permission denied|ya tiene boletas|no permitido",
    ):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_quien_dejo_el_registro_solo_ve_los_meses_en_que_tuvo_cargo(
    notario: AsyncClient,
    client: AsyncClient,
    escenario: Escenario,
    db_session: AsyncSession,
) -> None:
    from datetime import date

    from sqlalchemy import update

    from app.modules.padron.models import Adscripcion

    # El adscripto tiene cuenta y dejó el registro a fines de agosto.
    ex_user = await make_user(db_session)
    escenario.adscripto.user_id = ex_user.id
    await db_session.execute(
        update(Adscripcion)
        .where(Adscripcion.escribano_id == escenario.adscripto.id)
        .values(fecha_hasta=date(2026, 8, 31), is_current=False, motivo_cierre="Prueba")
    )
    await db_session.commit()
    agosto = (
        await notario.post(
            "/api/v1/ddjj/declaraciones",
            json={"registro_id": str(escenario.registro.id), "periodo": "2026-08"},
        )
    ).json()
    setiembre_id, boleta_id = await _presentada(notario, escenario)
    await login(client, ex_user)

    assert (await client.get(f"/api/v1/ddjj/declaraciones/{agosto['id']}")).status_code == 200
    assert (await client.get(f"/api/v1/ddjj/declaraciones/{setiembre_id}")).status_code == 404
    assert (await client.get(f"/api/v1/ddjj/boletas/{boleta_id}")).status_code == 404
    listado = (await client.get("/api/v1/ddjj/declaraciones")).json()
    assert [d["id"] for d in listado["items"]] == [agosto["id"]]
    # Ya no tiene cargo vigente: no opera.
    assert (await client.get(f"/api/v1/ddjj/declaraciones/{agosto['id']}")).json()[
        "puede_operar"
    ] is False


async def test_el_escribano_no_ve_correos_del_personal(
    notario: AsyncClient, staff: AsyncClient, escenario: Escenario
) -> None:
    ddjj = (
        await staff.post(
            "/api/v1/ddjj/declaraciones",
            json={"registro_id": str(escenario.registro.id), "periodo": "2026-09"},
        )
    ).json()
    boleta = (
        await staff.post(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar",
            json={"fecha_pago": "2026-10-23"},
        )
    ).json()

    visto_por_caja = (await staff.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    visto_por_escribano = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()

    assert "@" in boleta["emitida_por"]
    assert "@" in visto_por_caja["presentada_por"]
    assert visto_por_escribano["presentada_por"] == "Caja Notarial"
    assert visto_por_escribano["boletas"][0]["emitida_por"] == "Caja Notarial"


@pytest.mark.parametrize("periodo", ["0000-01", "1999-12", "2101-01", "2026-13"])
async def test_periodo_fuera_de_rango(
    notario: AsyncClient, escenario: Escenario, periodo: str
) -> None:
    response = await notario.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.registro.id), "periodo": periodo},
    )

    assert response.status_code == 422
