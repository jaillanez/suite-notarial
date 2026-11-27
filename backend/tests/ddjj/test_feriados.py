"""Feriados nacionales (Caja, 26/11/2026): bloquean la fecha de una escritura y la fecha de
pago de una boleta, como sábado y domingo. Las fechas de estas pruebas son sintéticas, no el
calendario oficial: el calendario lo carga la Caja."""

from collections.abc import AsyncIterator
from typing import Any

import pyotp
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from tests.conftest import CSRF_HEADERS
from tests.ddjj.conftest import Escenario, escritura
from tests.ddjj.test_flujo import _borrador, _cargar_1069, _presentar
from tests.iam.factories import make_user
from tests.iam.test_rbac import login

URL = "/api/v1/parametros/feriados"


@pytest.fixture
async def admin(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret=secret)
    transport = ASGITransport(app=app, client=("203.0.113.21", 52000))
    async with AsyncClient(
        transport=transport, base_url="https://test", headers=CSRF_HEADERS
    ) as ac:
        await login(ac, user, secret)
        yield ac


async def _feriado(admin: AsyncClient, fecha: str, descripcion: str = "Feriado de prueba") -> Any:
    r = await admin.post(URL, json={"fecha": fecha, "descripcion": descripcion})
    assert r.status_code == 201, r.text
    return r.json()


async def test_alta_baja_y_permisos(
    admin: AsyncClient, notario: AsyncClient, db_session: AsyncSession
) -> None:
    # El escribano consulta el calendario (para proponer el próximo hábil), pero no lo carga.
    assert (
        await notario.post(URL, json={"fecha": "2026-10-27", "descripcion": "X"})
    ).status_code == 403
    creado = await _feriado(admin, "2026-10-27")
    assert (
        await admin.post(URL, json={"fecha": "2026-10-27", "descripcion": "Otro"})
    ).status_code == 409
    sabado = await admin.post(URL, json={"fecha": "2026-10-24", "descripcion": "Sábado"})
    assert sabado.status_code == 422
    lista = (await notario.get(URL, params={"anio": 2026})).json()
    assert [(f["fecha"], f["is_active"]) for f in lista] == [("2026-10-27", True)]

    sin_motivo = await admin.post(f"{URL}/{creado['id']}/baja", json={"motivo": "x"})
    assert sin_motivo.status_code == 422
    baja = await admin.post(f"{URL}/{creado['id']}/baja", json={"motivo": "Cargado por error"})
    assert baja.status_code == 200, baja.text
    assert baja.json()["is_active"] is False
    # Dado de baja, el mismo día se puede volver a cargar.
    await _feriado(admin, "2026-10-27", "Corregido")
    # El escribano ve solo los vigentes, sin motivos de baja; la Caja ve el historial.
    del_escribano = (await notario.get(URL, params={"anio": 2026})).json()
    assert [(f["descripcion"], f["baja_motivo"]) for f in del_escribano] == [("Corregido", None)]
    del_admin = (await admin.get(URL, params={"anio": 2026})).json()
    assert len(del_admin) == 2
    eventos = (
        await db_session.scalars(
            select(AuditSecurityLog.event_type).where(
                AuditSecurityLog.event_type.like("PARAMETRO_FERIADO_%")
            )
        )
    ).all()
    assert sorted(eventos) == [
        "PARAMETRO_FERIADO_BAJA",
        "PARAMETRO_FERIADO_CREADO",
        "PARAMETRO_FERIADO_CREADO",
    ]
    # Sin borrado físico (INM).
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text("DELETE FROM parametros_feriados"))


async def test_no_se_carga_una_escritura_en_feriado(
    admin: AsyncClient, notario: AsyncClient, escenario: Escenario
) -> None:
    await _feriado(admin, "2026-09-16")
    ddjj = await _borrador(notario, escenario, "2026-09")
    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/actos"
    feriado = await notario.post(
        url, json=escritura(escenario.titular, 1, "1000", fecha_acto="2026-09-16")
    )
    assert feriado.status_code == 409
    assert "feriado nacional" in feriado.json()["detail"]
    habil = await notario.post(
        url, json=escritura(escenario.titular, 1, "1000", fecha_acto="2026-09-17")
    )
    assert habil.status_code == 201, habil.text


async def test_la_boleta_no_se_paga_en_feriado(
    admin: AsyncClient, notario: AsyncClient, escenario: Escenario
) -> None:
    await _feriado(admin, "2026-10-26", "Feriado sintético")
    ddjj = await _cargar_1069(notario, escenario)
    r = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-26"}
    )
    assert r.status_code == 422
    assert "feriado nacional (Feriado sintético)" in r.json()["detail"]
    assert len(await _presentar(notario, ddjj["id"], "2026-10-27")) == 2
