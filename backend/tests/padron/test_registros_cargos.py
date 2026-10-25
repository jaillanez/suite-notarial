import pyotp
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import FakeMailer
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.padron.conftest import Factory, valid_cuit

DATE = "2026-01-15"


async def _assign(caja: AsyncClient, escribano_id: str, registro_id: str, cargo: str) -> int:
    response = await caja.post(
        f"/api/v1/padron/escribanos/{escribano_id}/cargos",
        json={"registro_id": registro_id, "cargo": cargo, "fecha_desde": DATE},
    )
    return response.status_code


async def test_registro_starts_vacant_and_titular_activates_it(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    titular = await escribano()
    assert reg["estado"] == "VACANTE"

    assert await _assign(caja, titular["id"], reg["id"], "TITULAR") == 201

    detail = (await caja.get(f"/api/v1/padron/registros/{reg['id']}")).json()
    assert detail["estado"] == "ACTIVO"
    assert detail["titular"]["escribano_id"] == titular["id"]


async def test_single_titular_and_titular_adscripto_relation(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    titular, otro, adscripto = await escribano(), await escribano(), await escribano()

    assert await _assign(caja, titular["id"], reg["id"], "TITULAR") == 201
    assert await _assign(caja, otro["id"], reg["id"], "TITULAR") == 409
    assert await _assign(caja, adscripto["id"], reg["id"], "ADSCRIPTO") == 201

    detail = (await caja.get(f"/api/v1/padron/registros/{reg['id']}")).json()
    assert detail["cantidad_adscriptos"] == 1
    cargos = {c["escribano_id"]: c["cargo"] for c in detail["cargos_vigentes"]}
    assert cargos == {titular["id"]: "TITULAR", adscripto["id"]: "ADSCRIPTO"}


async def test_one_current_cargo_per_escribano(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    first, second = await registro(), await registro()
    esc = await escribano()

    assert await _assign(caja, esc["id"], first["id"], "ADSCRIPTO") == 201
    assert await _assign(caja, esc["id"], second["id"], "ADSCRIPTO") == 409


async def test_closing_titular_leaves_registro_vacant_and_keeps_history(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    titular = await escribano()
    await _assign(caja, titular["id"], reg["id"], "TITULAR")
    cargo_id = (await caja.get(f"/api/v1/padron/escribanos/{titular['id']}")).json()["cargos"][0][
        "id"
    ]

    closed = await caja.post(
        f"/api/v1/padron/cargos/{cargo_id}/cierre",
        json={"fecha_hasta": "2026-06-30", "motivo": "Renuncia aceptada por Res. 12/2026"},
    )

    assert closed.status_code == 200
    assert closed.json()["is_current"] is False
    detail = (await caja.get(f"/api/v1/padron/registros/{reg['id']}")).json()
    assert detail["estado"] == "VACANTE"
    assert detail["titular"] is None
    history = (await caja.get(f"/api/v1/padron/escribanos/{titular['id']}")).json()["cargos"]
    assert history[0]["fecha_hasta"] == "2026-06-30"


async def test_definitive_state_requires_closing_cargos(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    esc = await escribano()
    await _assign(caja, esc["id"], reg["id"], "ADSCRIPTO")

    response = await caja.post(
        f"/api/v1/padron/escribanos/{esc['id']}/estado",
        json={"nuevo_estado": "CESANTE", "motivo": "Cese por resolución", "fecha_efectiva": DATE},
    )

    assert response.status_code == 409
    assert "cargo vigente" in response.json()["detail"]


async def test_only_active_escribano_can_take_cargo(
    caja: AsyncClient, registro: Factory, escribano: Factory
) -> None:
    reg = await registro()
    esc = await escribano()
    await caja.post(
        f"/api/v1/padron/escribanos/{esc['id']}/estado",
        json={
            "nuevo_estado": "SUSPENDIDO",
            "motivo": "Suspensión preventiva",
            "fecha_efectiva": DATE,
        },
    )

    assert await _assign(caja, esc["id"], reg["id"], "ADSCRIPTO") == 409


async def test_closed_registro_rejects_changes(caja: AsyncClient, registro: Factory) -> None:
    reg = await registro()

    closed = await caja.post(
        f"/api/v1/padron/registros/{reg['id']}/cierre", json={"motivo": "Supresión del registro"}
    )
    edit = await caja.patch(f"/api/v1/padron/registros/{reg['id']}", json={"telefono": "1"})

    assert closed.status_code == 200
    assert closed.json()["estado"] == "CERRADO"
    assert edit.status_code == 409


async def test_registro_validations(
    caja: AsyncClient, registro: Factory, circunscripcion: Factory
) -> None:
    reg = await registro()
    circ = await circunscripcion()

    duplicate = await caja.post(
        "/api/v1/padron/registros",
        json={
            "numero_registro": reg["numero_registro"],
            "circunscripcion_id": circ["id"],
            "departamento": "Capital",
            "domicilio_legal": "Otra 1",
        },
    )
    bad_departamento = await caja.post(
        "/api/v1/padron/registros",
        json={
            "numero_registro": 99_999,
            "circunscripcion_id": circ["id"],
            "departamento": "Córdoba",
            "domicilio_legal": "Otra 1",
        },
    )

    assert duplicate.status_code == 409
    assert bad_departamento.status_code == 422


async def test_registro_filters(caja: AsyncClient, registro: Factory) -> None:
    reg = await registro(nombre_fantasia="Escribanía del Parque", departamento="Rivadavia")

    by_number = await caja.get(
        "/api/v1/padron/registros", params={"q": str(reg["numero_registro"])}
    )
    by_name = await caja.get("/api/v1/padron/registros", params={"q": "parque"})
    by_dep = await caja.get("/api/v1/padron/registros", params={"departamento": "Rivadavia"})

    assert [r["id"] for r in by_number.json()["items"]] == [reg["id"]]
    assert [r["id"] for r in by_name.json()["items"]] == [reg["id"]]
    assert reg["id"] in [r["id"] for r in by_dep.json()["items"]]


async def test_self_service_account(
    caja: AsyncClient, escribano: Factory, client: AsyncClient
) -> None:
    esc = await escribano(email="escribano.sintetico@suite-notarial.example")

    # Caja no tiene users:write: no puede crear cuentas.
    denied = await caja.post(f"/api/v1/padron/escribanos/{esc['id']}/cuenta")
    assert denied.status_code == 403


async def test_admin_creates_self_service_account(
    client: AsyncClient, db_session: AsyncSession, mailer: FakeMailer
) -> None:
    secret = pyotp.random_base32()
    admin = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    await login(client, admin, secret)
    circ = await client.post("/api/v1/padron/circunscripciones", json={"nombre": "Circ. cuenta"})
    assert circ.status_code == 201
    created = await client.post(
        "/api/v1/padron/escribanos",
        json={
            "persona": {
                "cuit": valid_cuit(),
                "numero_documento": "30999888",
                "apellido": "Cuenta",
                "nombre": "Autogestión",
            },
            "matricula_numero": 424_242,
            "fecha_matriculacion": "2015-03-01",
        },
    )
    esc_id = created.json()["id"]

    without_email = await client.post(f"/api/v1/padron/escribanos/{esc_id}/cuenta")
    assert without_email.status_code == 422

    await client.patch(
        f"/api/v1/padron/escribanos/{esc_id}",
        json={"persona": {"email": "Cuenta.Autogestion@suite-notarial.example"}},
    )
    response = await client.post(f"/api/v1/padron/escribanos/{esc_id}/cuenta")

    assert response.status_code == 201
    assert response.json()["tiene_cuenta"] is True
    assert mailer.sent[-1].to == "cuenta.autogestion@suite-notarial.example"
    again = await client.post(f"/api/v1/padron/escribanos/{esc_id}/cuenta")
    assert again.status_code == 409
