"""Carga rápida: la DDJJ propone el número de escritura que sigue en cada protocolo."""

from httpx import AsyncClient

from tests.ddjj.conftest import Escenario, escritura
from tests.ddjj.test_protocolo import _agregar, _borrador


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
