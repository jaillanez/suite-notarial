"""Carga rápida: la DDJJ propone el número de escritura que sigue en cada protocolo."""

from datetime import date

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.padron.models import Adscripcion
from tests.ddjj.conftest import Escenario, _client, _escribano, escritura
from tests.ddjj.test_protocolo import _agregar, _borrador
from tests.iam.factories import make_user
from tests.iam.test_rbac import login


async def test_propone_el_numero_que_sigue_en_el_anio(
    notario: AsyncClient, escenario: Escenario
) -> None:
    agosto = await _borrador(notario, escenario, "2026-08")
    vacia = (await notario.get(f"/api/v1/ddjj/declaraciones/{agosto['id']}")).json()
    assert vacia["proximos_numeros"] == {"GENERAL": 1, "AUXILIAR": 1}

    for numero in (40, 41):
        acto = escritura(escenario.titular, numero, "1000", fecha_acto="2026-08-10")
        assert (await _agregar(notario, agosto["id"], acto)).status_code == 201
    auxiliar = escritura(
        escenario.titular, 7, "1000", fecha_acto="2026-08-11", tipo_protocolo="AUXILIAR"
    )
    assert (await _agregar(notario, agosto["id"], auxiliar)).status_code == 201

    # En otro mes del mismo año la numeración sigue la del registro, no la de la DDJJ.
    setiembre = await _borrador(notario, escenario, "2026-09")
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{setiembre['id']}")).json()
    assert detalle["proximos_numeros"] == {"GENERAL": 42, "AUXILIAR": 8}


async def test_solo_cuenta_los_meses_que_quien_consulta_puede_ver(
    app: FastAPI, staff: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    """Un ex adscripto ve sus DDJJ, pero no la numeración de los meses posteriores a su cargo."""
    user = await make_user(db_session)
    ex = await _escribano(db_session, "ExAdscripto", user)
    db_session.add(
        Adscripcion(
            escribano_id=ex.id,
            registro_id=escenario.registro.id,
            cargo="ADSCRIPTO",
            fecha_desde=date(2020, 1, 1),
            fecha_hasta=date(2026, 8, 31),
            is_current=False,
        )
    )
    await db_session.commit()
    agosto = await _borrador(staff, escenario, "2026-08")
    acto = escritura(escenario.titular, 40, "1000", fecha_acto="2026-08-10")
    assert (await _agregar(staff, agosto["id"], acto)).status_code == 201
    setiembre = await _borrador(staff, escenario, "2026-09")
    acto = escritura(escenario.titular, 60, "1000", fecha_acto="2026-09-10")
    assert (await _agregar(staff, setiembre["id"], acto)).status_code == 201

    async with await _client(app) as cliente:
        await login(cliente, user)
        detalle = (await cliente.get(f"/api/v1/ddjj/declaraciones/{agosto['id']}")).json()
    assert detalle["proximos_numeros"]["GENERAL"] == 41
