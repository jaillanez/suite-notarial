from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.padron.models import Escribano, HistorialEstado
from tests.padron.conftest import Factory, valid_cuit


async def test_create_and_read_escribano(caja: AsyncClient, escribano: Factory) -> None:
    created = await escribano(apellido="Sarmiento", nombre="Domingo")

    assert created["estado_matricula"] == "ACTIVO"
    assert created["apellido_nombre"] == "Sarmiento, Domingo"
    assert created["persona"]["cuit"].count("-") == 2
    detail = await caja.get(f"/api/v1/padron/escribanos/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["historial"] == []


async def test_invalid_cuit_is_rejected_before_db(caja: AsyncClient) -> None:
    good = valid_cuit()
    bad = good[:10] + str((int(good[10]) + 1) % 10)
    response = await caja.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {
                "cuit": bad,
                "numero_documento": "30111222",
                "apellido": "Prueba",
                "nombre": "Inválido",
            },
            "matricula_numero": 1,
            "fecha_matriculacion": "2015-03-01",
        },
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"][-1] == "cuit"


async def test_duplicates_are_conflicts(caja: AsyncClient, escribano: Factory) -> None:
    first = await escribano()
    cuit = first["persona"]["cuit"]

    dup_cuit = await caja.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {
                "cuit": cuit,
                "numero_documento": "1234567",
                "apellido": "Ab",
                "nombre": "Cd",
            },
            "matricula_numero": 777_001,
            "fecha_matriculacion": "2015-03-01",
        },
    )
    dup_matricula = await caja.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {
                "cuit": valid_cuit(),
                "numero_documento": "1234567",
                "apellido": "Ab",
                "nombre": "Cd",
            },
            "matricula_numero": first["matricula_numero"],
            "fecha_matriculacion": "2015-03-01",
        },
    )

    assert dup_cuit.status_code == 409
    assert dup_cuit.json()["detail"] == "Ya hay una persona registrada con ese CUIT."
    assert dup_matricula.status_code == 409
    assert dup_matricula.json()["detail"] == "Ese número de matrícula ya está asignado."


async def test_status_change_keeps_row_and_writes_history(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    created = await escribano()

    response = await caja.post(
        f"/api/v1/padron/escribanos/{created['id']}/estado",
        json={
            "nuevo_estado": "SUSPENDIDO",
            "motivo": "Licencia extraordinaria por cargo público",
            "resolucion_respaldo": "Res. 89/2026",
            "fecha_efectiva": "2026-10-01",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["estado_matricula"] == "SUSPENDIDO"
    assert body["historial"][0]["estado_anterior"] == "ACTIVO"
    assert body["historial"][0]["operador_email"]
    listed = await caja.get(
        "/api/v1/padron/escribanos", params={"q": str(created["matricula_numero"])}
    )
    assert listed.json()["items"][0]["estado_matricula"] == "SUSPENDIDO"
    audit = (
        await db_session.execute(
            select(AuditSecurityLog).where(AuditSecurityLog.event_type == "PADRON_ESTADO_CHANGED")
        )
    ).scalar_one()
    assert audit.old_value == {"estado_matricula": "ACTIVO"}
    assert audit.new_value == {"estado_matricula": "SUSPENDIDO"}
    assert audit.details is not None
    assert audit.details["motivo"] == "Licencia extraordinaria por cargo público"


async def test_terminal_state_cannot_change(caja: AsyncClient, escribano: Factory) -> None:
    created = await escribano()
    url = f"/api/v1/padron/escribanos/{created['id']}/estado"
    base: dict[str, Any] = {"motivo": "Constancia de defunción", "fecha_efectiva": "2026-10-01"}

    assert (await caja.post(url, json={**base, "nuevo_estado": "FALLECIDO"})).status_code == 200
    again = await caja.post(url, json={**base, "nuevo_estado": "ACTIVO"})
    assert again.status_code == 409


async def test_motivo_is_mandatory(caja: AsyncClient, escribano: Factory) -> None:
    created = await escribano()

    response = await caja.post(
        f"/api/v1/padron/escribanos/{created['id']}/estado",
        json={"nuevo_estado": "SUSPENDIDO", "motivo": "x", "fecha_efectiva": "2026-10-01"},
    )

    assert response.status_code == 422


async def test_update_is_audited_with_changed_fields_only(
    caja: AsyncClient, escribano: Factory, db_session: AsyncSession
) -> None:
    created = await escribano()

    response = await caja.patch(
        f"/api/v1/padron/escribanos/{created['id']}",
        json={"tomo": "IV", "persona": {"telefono": "264 4000000"}},
    )

    assert response.status_code == 200
    audit = (
        await db_session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "PADRON_ESCRIBANO_UPDATED"
            )
        )
    ).scalar_one()
    assert audit.old_value == {"telefono": None, "tomo": None}
    assert audit.new_value == {"telefono": "264 4000000", "tomo": "IV"}


async def test_search_and_filters(caja: AsyncClient, escribano: Factory) -> None:
    target = await escribano(apellido="Quiroga", nombre="Facundo", numero_documento="31555666")
    await escribano(apellido="Otro", nombre="Apellido")

    by_name = await caja.get("/api/v1/padron/escribanos", params={"q": "quirog"})
    by_dni = await caja.get("/api/v1/padron/escribanos", params={"q": "31555666"})
    by_cuit = await caja.get("/api/v1/padron/escribanos", params={"q": target["persona"]["cuit"]})
    by_state = await caja.get("/api/v1/padron/escribanos", params={"estado": "CESANTE"})

    assert [i["id"] for i in by_name.json()["items"]] == [target["id"]]
    assert [i["id"] for i in by_dni.json()["items"]] == [target["id"]]
    assert [i["id"] for i in by_cuit.json()["items"]] == [target["id"]]
    assert by_state.json()["total"] == 0


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM padron_escribanos",
        "DELETE FROM padron_personas",
        "TRUNCATE padron_registros_notariales CASCADE",
        "UPDATE padron_historial_estados SET motivo = 'x'",
    ],
)
async def test_application_role_cannot_delete_padron(
    db_session: AsyncSession, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_no_physical_delete_in_models() -> None:
    # El código del padrón no expone borrado: ninguna ruta DELETE.
    from app.modules.padron.router import router

    assert not [r for r in router.routes if "DELETE" in getattr(r, "methods", set())]
    assert Escribano.__tablename__ and HistorialEstado.__tablename__


async def test_escribano_role_cannot_read_padron(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    user = await make_user(db_session)
    await login(client, user)

    assert (await client.get("/api/v1/padron/escribanos")).status_code == 403
