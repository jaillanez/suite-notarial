"""La DDJJ con el formato de la planilla de la Caja: protocolos, resumen y PDF.

El caso es el del ejemplo de la planilla «Declaración Jurada de Aportes»: una venta del titular
en el protocolo general que paga el mínimo y una donación del adscripto (aporte fijo). Los
montos son los vigentes desde junio 2026 (mínimo 57.289; fijo mayor 37.446).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ddjj.catalog import CategoriaActo, TipoProtocolo
from app.modules.ddjj.liquidacion import AporteActo
from app.modules.ddjj.planilla import ActoPlanilla, armar
from app.modules.padron.catalog import Cargo
from tests.ddjj.conftest import Escenario, escritura
from tests.ddjj.test_protocolo import _agregar, _borrador
from tests.iam.factories import make_user
from tests.iam.test_rbac import login

D = Decimal


def _acto(
    numero: int,
    categoria: CategoriaActo,
    cargo: Cargo = Cargo.TITULAR,
    *,
    protocolo: TipoProtocolo = TipoProtocolo.GENERAL,
    folio: int | None = None,
    orden: int = 1,
) -> ActoPlanilla:
    base = D("1000000.00") if categoria is CategoriaActo.ESCRITURA_CON_VALOR else D("0.00")
    return ActoPlanilla(protocolo, numero, orden, folio, "Acto", categoria, base, "X", cargo)


def test_columnas_y_totales_como_la_planilla() -> None:
    actos = [
        _acto(34, CategoriaActo.OTRO_ACTO, Cargo.ADSCRIPTO, folio=240),
        _acto(33, CategoriaActo.ESCRITURA_CON_VALOR, folio=234),
        _acto(5, CategoriaActo.ACTA_O_PODER, protocolo=TipoProtocolo.AUXILIAR),
    ]
    aportes = [
        AporteActo(D("37446.00"), None),
        AporteActo(D("57289.00"), None),
        AporteActo(D("9922.00"), None),
    ]
    planilla = armar(actos, aportes)
    general, auxiliar = planilla.protocolos
    # Ordenada por número de escritura, como el libro.
    assert [r.numero_escritura for r in general.renglones] == [33, 34]
    venta, donacion = general.renglones
    assert (venta.base_imponible, venta.aporte_variable, venta.aporte_fijo) == (
        D("1000000.00"),
        D("57289.00"),
        None,
    )
    assert (donacion.base_imponible, donacion.aporte_variable, donacion.aporte_fijo) == (
        None,
        None,
        D("37446.00"),
    )
    # El total de «Aporte» suma los aportes, no el 0,4 % del encabezado (error de la planilla).
    assert general.totales.aporte_variable == D("57289.00")
    assert general.totales.por_cargo == {
        Cargo.TITULAR: D("57289.00"),
        Cargo.ADSCRIPTO: D("37446.00"),
        Cargo.SUPLENTE_INTERINO: D("0.00"),
    }
    # El resumen calcula solo los rangos de escrituras y folios.
    assert (general.escrituras_desde, general.escrituras_hasta) == (33, 34)
    assert (general.folios_desde, general.folios_hasta) == (234, 240)
    assert (auxiliar.folios_desde, auxiliar.folios_hasta) == (None, None)
    assert planilla.totales.total == D("104657.00")


def test_acto_incluido_en_el_principal() -> None:
    actos = [
        _acto(10, CategoriaActo.ESCRITURA_CON_VALOR),
        _acto(10, CategoriaActo.OTRO_ACTO, orden=2),
    ]
    aportes = [
        AporteActo(D("57289.00"), None),
        AporteActo(D("0.00"), None, individual=D("37446.00")),
    ]
    general = armar(actos, aportes).protocolos[0]
    donacion = general.renglones[1]
    assert donacion.incluido_en_otro
    assert (donacion.aporte_fijo, donacion.aporte) == (D("37446.00"), D("0.00"))
    # La columna del cargo suma lo que se paga; la de aporte fijo, lo que aporta el acto solo.
    assert general.totales.por_cargo[Cargo.TITULAR] == D("57289.00")
    assert general.totales.aporte_fijo == D("37446.00")


def test_sin_aportes_calculados() -> None:
    planilla = armar([_acto(1, CategoriaActo.ESCRITURA_CON_VALOR)], None)
    assert not planilla.con_aportes
    renglon = planilla.protocolos[0].renglones[0]
    assert renglon.aporte is None and renglon.aporte_variable is None
    assert planilla.totales.total == D("0.00")
    with pytest.raises(ValueError, match="aporte"):
        armar([_acto(1, CategoriaActo.ACTA_O_PODER)], [])


async def test_planilla_y_pdf_de_un_borrador_y_de_la_presentada(
    notario: AsyncClient, escenario: Escenario
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    venta = escritura(escenario.titular, 33, "1000000", folio=234)
    assert (await _agregar(notario, ddjj["id"], venta)).status_code == 201
    poder = {
        **escritura(escenario.adscripto, 34, "0", folio=240),
        "naturaleza": "Poder general",
        "categoria": "ACTA_O_PODER",
    }
    assert (await _agregar(notario, ddjj["id"], poder)).status_code == 201

    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}"
    borrador = (await notario.get(f"{url}/planilla")).json()
    assert borrador["estado"] == "BORRADOR"
    assert borrador["titulares"] == ["TITULAR, Sintético"]
    assert borrador["adscriptos"] == ["ADSCRIPTO, Sintético"]
    general = borrador["protocolos"][0]
    assert general["tipo"] == "GENERAL"
    assert [r["cargo"] for r in general["renglones"]] == ["TITULAR", "ADSCRIPTO"]
    assert general["totales"]["titular"] == "57289.00"
    assert general["totales"]["adscripto"] == "9922.00"
    assert (general["escrituras_desde"], general["escrituras_hasta"]) == (33, 34)
    assert borrador["totales"]["total"] == "67211.00"

    pdf = await notario.get(f"{url}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert "ddjj-registro-" in pdf.headers["content-disposition"]

    presentada = await notario.post(f"{url}/presentar", json={"fecha_pago": "2026-10-23"})
    assert presentada.status_code == 201, presentada.text
    final = (await notario.get(f"{url}/planilla")).json()
    assert final["estado"] == "PRESENTADA"
    assert final["fecha_presentacion"] is not None
    # Lo congelado al presentar es lo mismo que mostraba el borrador.
    assert final["totales"] == borrador["totales"]


async def test_la_planilla_respeta_el_acceso(
    notario: AsyncClient,
    staff: AsyncClient,
    escenario: Escenario,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}"
    # La Caja la consulta.
    assert (await staff.get(f"{url}/planilla")).status_code == 200
    # Un escribano sin cargo en el registro no la ve (ni la planilla ni el PDF).
    otro = await make_user(db_session)
    await login(client, otro)
    assert (await client.get(f"{url}/planilla")).status_code == 404
    assert (await client.get(f"{url}/pdf")).status_code == 404
