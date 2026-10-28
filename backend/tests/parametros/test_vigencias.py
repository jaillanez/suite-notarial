"""Vigencias: versionado sin sobreescritura, sin solapamiento, cuatro ojos y resolución por fecha.

Los valores son sintéticos de prueba, no parámetros oficiales de la Caja.
"""

from itertools import count
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.parametros import service

_codes = count(1)


async def concepto(c: AsyncClient, tipo: str = "PORCENTUAL_ACTO") -> dict[str, Any]:
    response = await c.post(
        "/api/v1/parametros/conceptos",
        json={"codigo": f"PRUEBA_{next(_codes)}", "nombre": "Concepto de prueba", "tipo": tipo},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def proponer(c: AsyncClient, concepto_id: str, **values: Any) -> Any:
    payload = {
        "resolucion_respaldo": "Res. de prueba 1/2026",
        "motivo": "Valor sintético de prueba",
        **values,
    }
    return await c.post(f"/api/v1/parametros/conceptos/{concepto_id}/vigencias", json=payload)


async def vigente(
    proponente: AsyncClient, aprobador: AsyncClient, concepto_id: str, **values: Any
) -> dict[str, Any]:
    proposed = await proponer(proponente, concepto_id, **values)
    assert proposed.status_code == 201, proposed.text
    approved = await aprobador.post(f"/api/v1/parametros/vigencias/{proposed.json()['id']}/aprobar")
    assert approved.status_code == 200, approved.text
    body: dict[str, Any] = approved.json()
    return body


async def test_proposal_needs_another_person(
    proponente: AsyncClient, aprobador: AsyncClient
) -> None:
    c = await concepto(proponente)
    proposed = await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1.5")

    assert proposed.status_code == 201
    assert proposed.json()["estado"] == "PENDIENTE_APROBACION"
    assert proposed.json()["porcentaje"] == "1.5000"
    self_approval = await proponente.post(
        f"/api/v1/parametros/vigencias/{proposed.json()['id']}/aprobar"
    )
    assert self_approval.status_code == 403
    approved = await aprobador.post(f"/api/v1/parametros/vigencias/{proposed.json()['id']}/aprobar")
    assert approved.json()["estado"] == "VIGENTE"
    assert approved.json()["aprobado_por"]


async def test_resolution_by_date_and_new_version_closes_previous(
    proponente: AsyncClient, aprobador: AsyncClient, db_session: AsyncSession
) -> None:
    c = await concepto(proponente)
    v1 = await vigente(proponente, aprobador, c["id"], fecha_desde="2026-01-01", porcentaje="1.0")
    v2 = await vigente(proponente, aprobador, c["id"], fecha_desde="2026-07-01", porcentaje="2.0")

    history = (await proponente.get(f"/api/v1/parametros/conceptos/{c['id']}/vigencias")).json()
    old = next(v for v in history if v["id"] == v1["id"])
    assert old["fecha_hasta"] == "2026-06-30"
    assert old["porcentaje"] == "1.0000"  # el valor anterior no cambió
    assert v2["version"] == 2

    from datetime import date

    for fecha, esperado in [
        (date(2026, 1, 1), v1["id"]),
        (date(2026, 6, 30), v1["id"]),
        (date(2026, 7, 1), v2["id"]),
        (date(2030, 1, 1), v2["id"]),
    ]:
        snap = await service.get_vigencia(db_session, c["codigo"], fecha)
        assert str(snap.vigencia_id) == esperado

    with pytest.raises(Exception, match="No hay una vigencia aprobada"):
        await service.get_vigencia(db_session, c["codigo"], date(2025, 12, 31))

    closed = (
        await db_session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "PARAMETRO_VIGENCIA_CERRADA"
            )
        )
    ).scalar_one()
    assert closed.new_value == {"fecha_hasta": "2026-06-30"}


async def test_overlaps_are_rejected(proponente: AsyncClient, aprobador: AsyncClient) -> None:
    c = await concepto(proponente)
    await vigente(
        proponente,
        aprobador,
        c["id"],
        fecha_desde="2026-01-01",
        fecha_hasta="2026-06-30",
        porcentaje="1.0",
    )

    inside = await proponer(proponente, c["id"], fecha_desde="2026-03-01", porcentaje="2.0")
    before_open = await proponer(proponente, c["id"], fecha_desde="2025-06-01", porcentaje="2.0")
    ok = await proponer(proponente, c["id"], fecha_desde="2026-07-01", porcentaje="2.0")
    pending_overlap = await proponer(
        proponente, c["id"], fecha_desde="2026-08-01", porcentaje="3.0"
    )

    assert inside.status_code == 409
    assert "superponen" in inside.json()["detail"]
    assert before_open.status_code == 409
    assert ok.status_code == 201
    assert pending_overlap.status_code == 409
    assert "pendiente" in pending_overlap.json()["detail"]


async def test_values_must_match_type(proponente: AsyncClient) -> None:
    pct = await concepto(proponente, "PORCENTUAL_ACTO")
    mora = await concepto(proponente, "TASA_MORA")

    missing = await proponer(proponente, pct["id"], fecha_desde="2026-01-01")
    wrong = await proponer(
        proponente,
        mora["id"],
        fecha_desde="2026-01-01",
        tasa="3",
        periodo_tasa="MENSUAL",
        dias_gracia=0,
        monto_fijo="10",
    )
    sin_unidad = await proponer(proponente, mora["id"], fecha_desde="2026-01-01", tasa="3")
    bad_range = await proponer(
        proponente,
        pct["id"],
        fecha_desde="2026-02-01",
        fecha_hasta="2026-01-01",
        porcentaje="1",
    )
    too_precise = await proponer(
        proponente, pct["id"], fecha_desde="2026-01-01", porcentaje="1.23456"
    )

    assert missing.status_code == 422
    assert "faltan porcentaje" in missing.json()["detail"]
    assert wrong.status_code == 422
    assert sin_unidad.status_code == 422
    assert "periodo_tasa" in sin_unidad.json()["detail"]
    assert bad_range.status_code == 422
    assert too_precise.status_code == 422


async def test_rejection_is_final(proponente: AsyncClient, aprobador: AsyncClient) -> None:
    c = await concepto(proponente)
    proposed = await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1")
    vid = proposed.json()["id"]

    rejected = await aprobador.post(
        f"/api/v1/parametros/vigencias/{vid}/rechazar", json={"motivo": "Falta resolución firmada"}
    )
    approve_after = await aprobador.post(f"/api/v1/parametros/vigencias/{vid}/aprobar")

    assert rejected.json()["estado"] == "RECHAZADA"
    assert approve_after.status_code == 409
    again = await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1.1")
    assert again.status_code == 201  # una rechazada no bloquea fechas


async def test_changes_are_audited(
    proponente: AsyncClient, aprobador: AsyncClient, db_session: AsyncSession
) -> None:
    c = await concepto(proponente)
    v = await vigente(proponente, aprobador, c["id"], fecha_desde="2026-01-01", porcentaje="1.25")

    events = {
        row.event_type: row
        for row in (
            await db_session.execute(
                select(AuditSecurityLog).where(AuditSecurityLog.event_type.like("PARAMETRO_%"))
            )
        ).scalars()
    }
    assert {"PARAMETRO_CONCEPTO_CREATED", "PARAMETRO_VIGENCIA_PROPUESTA"} <= set(events)
    approved = events["PARAMETRO_VIGENCIA_APROBADA"]
    assert approved.old_value == {"estado": "PENDIENTE_APROBACION"}
    assert approved.new_value is not None
    assert approved.new_value["porcentaje"] == "1.2500"
    assert approved.details is not None
    assert approved.details["vigencia_id"] == v["id"]


async def test_database_enforces_immutability_and_no_overlap(
    proponente: AsyncClient, aprobador: AsyncClient, db_session: AsyncSession
) -> None:
    c = await concepto(proponente)
    v = await vigente(
        proponente,
        aprobador,
        c["id"],
        fecha_desde="2026-01-01",
        fecha_hasta="2026-12-31",
        porcentaje="1",
    )

    for statement in (
        "UPDATE parametros_vigencias SET porcentaje = 9 WHERE id = :id",
        "UPDATE parametros_vigencias SET fecha_hasta = '2027-12-31' WHERE id = :id",
        "UPDATE parametros_vigencias SET estado = 'RECHAZADA' WHERE id = :id",
        "DELETE FROM parametros_vigencias WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(statement), {"id": v["id"]})

    with pytest.raises(DBAPIError, match=r"ex_parametros_vigencias_sin_solapamiento"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO parametros_vigencias (id, concepto_id, version, fecha_desde, "
                    "porcentaje, estado, resolucion_respaldo, motivo, created_by_user_id, "
                    "aprobado_por_user_id) SELECT gen_random_uuid(), concepto_id, 99, "
                    "'2026-06-01', 2, 'VIGENTE', 'x', 'x', created_by_user_id, "
                    "aprobado_por_user_id FROM parametros_vigencias WHERE id = :id"
                ),
                {"id": v["id"]},
            )


async def test_permissions(client: AsyncClient, db_session: AsyncSession) -> None:
    import pyotp

    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    secret = pyotp.random_base32()
    caja = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    await login(client, caja, secret)

    assert (await client.get("/api/v1/parametros/conceptos")).status_code == 200
    denied = await client.post(
        "/api/v1/parametros/conceptos",
        json={"codigo": "NO_PERMITIDO", "nombre": "No permitido", "tipo": "FIJO_MENSUAL"},
    )
    assert denied.status_code == 403


async def test_simulation_uses_vigencia_at_date(
    proponente: AsyncClient, aprobador: AsyncClient
) -> None:
    c = await concepto(proponente)
    await vigente(
        proponente,
        aprobador,
        c["id"],
        fecha_desde="2026-01-01",
        porcentaje="1.5",
        monto_minimo="500",
    )

    sim = await proponente.post(
        "/api/v1/parametros/simulacion",
        json={"concepto_codigo": c["codigo"], "fecha": "2026-05-01", "base_imponible": "1000"},
    )
    none = await proponente.post(
        "/api/v1/parametros/simulacion",
        json={"concepto_codigo": c["codigo"], "fecha": "2025-05-01", "base_imponible": "1000"},
    )

    assert sim.status_code == 200
    assert sim.json()["resultado"] == "500.00"
    assert none.status_code == 422


async def test_retirar_una_propuesta_pendiente(
    proponente: AsyncClient, aprobador: AsyncClient, db_session: AsyncSession
) -> None:
    c = await concepto(proponente)
    vid = (await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1")).json()[
        "id"
    ]

    retirada = await proponente.post(
        f"/api/v1/parametros/vigencias/{vid}/retirar", json={"motivo": "Cargué mal el valor"}
    )
    assert retirada.status_code == 200, retirada.text
    assert retirada.json()["estado"] == "RETIRADA"
    assert retirada.json()["motivo_rechazo"] == "Cargué mal el valor"
    # Retirada no se aprueba ni se vuelve a retirar, y no bloquea sus fechas.
    assert (await aprobador.post(f"/api/v1/parametros/vigencias/{vid}/aprobar")).status_code == 409
    otra = await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1.1")
    assert otra.status_code == 201
    eventos = (await db_session.scalars(select(AuditSecurityLog.event_type))).all()
    assert "PARAMETRO_VIGENCIA_RETIRADA" in eventos


async def test_corregir_deja_una_version_nueva_y_conserva_la_anterior(
    proponente: AsyncClient, aprobador: AsyncClient
) -> None:
    c = await concepto(proponente)
    original = (
        await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1")
    ).json()

    corregida = await proponente.put(
        f"/api/v1/parametros/vigencias/{original['id']}",
        json={
            "fecha_desde": "2026-02-01",
            "porcentaje": "1.25",
            "resolucion_respaldo": "Res. de prueba 2/2026",
            "motivo": "Corrijo porcentaje y fecha",
        },
    )
    assert corregida.status_code == 200, corregida.text
    nueva = corregida.json()
    assert nueva["id"] != original["id"]
    assert nueva["version"] == original["version"] + 1
    assert (nueva["estado"], nueva["porcentaje"], nueva["fecha_desde"]) == (
        "PENDIENTE_APROBACION",
        "1.2500",
        "2026-02-01",
    )
    vigencias = {
        v["id"]: v
        for v in (await proponente.get(f"/api/v1/parametros/conceptos/{c['id']}/vigencias")).json()
    }
    # La original no se modificó: quedó retirada con sus valores intactos.
    assert vigencias[original["id"]]["estado"] == "RETIRADA"
    assert vigencias[original["id"]]["porcentaje"] == "1.0000"
    aprobada = await aprobador.post(f"/api/v1/parametros/vigencias/{nueva['id']}/aprobar")
    assert aprobada.json()["estado"] == "VIGENTE"


async def test_solo_se_corrige_o_retira_lo_pendiente(
    proponente: AsyncClient, aprobador: AsyncClient
) -> None:
    c = await concepto(proponente)
    v = await vigente(proponente, aprobador, c["id"], fecha_desde="2026-01-01", porcentaje="1")

    retirar = await proponente.post(
        f"/api/v1/parametros/vigencias/{v['id']}/retirar", json={"motivo": "Quiero cambiarla"}
    )
    corregir = await proponente.put(
        f"/api/v1/parametros/vigencias/{v['id']}",
        json={
            "fecha_desde": "2026-01-01",
            "porcentaje": "2",
            "resolucion_respaldo": "Res. de prueba",
            "motivo": "Cambiar lo aprobado",
        },
    )
    assert retirar.status_code == 409
    assert corregir.status_code == 409


async def test_corregir_y_retirar_exigen_permiso(
    client: AsyncClient, proponente: AsyncClient, db_session: AsyncSession
) -> None:
    import pyotp

    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    c = await concepto(proponente)
    vid = (await proponer(proponente, c["id"], fecha_desde="2026-01-01", porcentaje="1")).json()[
        "id"
    ]
    secret = pyotp.random_base32()
    caja = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    await login(client, caja, secret)

    retirar = await client.post(
        f"/api/v1/parametros/vigencias/{vid}/retirar", json={"motivo": "Sin permiso"}
    )
    assert retirar.status_code == 403
