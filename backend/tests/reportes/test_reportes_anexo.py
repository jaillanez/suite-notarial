"""Reportes del Anexo I: actos declarados, aportes declarados y pagados por mes o año, notarios
sin DDJJ o sin pago, el filtro de atrasos y «Mis aportes» del escribano.

Escenario (`datos`): agosto 2026 con dos escrituras del titular y su boleta pagada; septiembre
con una escritura y la boleta del titular pendiente. El adscripto tiene sus boletas (mínimo y
médico) pendientes en los dos meses."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.reportes import catalogo
from tests.ddjj.conftest import HOY, Escenario
from tests.reportes.test_reportes import _pantalla, verificar_paridad

D = Decimal


@pytest.fixture(autouse=True)
def hoy_reportes(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """«Hoy» de los atrasos y del período por defecto (el mismo de las boletas)."""

    def poner(dia: date) -> None:
        monkeypatch.setattr(catalogo, "today_local", lambda: dia)

    poner(HOY)
    return poner


@pytest.mark.parametrize(
    ("codigo", "filtros"),
    [
        ("ACTOS", {}),
        ("ACTOS", {"categoria": "ESCRITURA_CON_VALOR", "pago": "PARCIAL"}),
        ("APORTES_PERIODO", {}),
        ("APORTES_PERIODO", {"agrupar": "ANIO"}),
        ("SIN_DDJJ_O_PAGO", {"periodo": "2026-09", "situacion": "TODOS"}),
        ("BOLETAS", {"atraso": "VENCIDA_IMPAGA"}),
    ],
)
async def test_paridad_pantalla_xlsx_csv(
    auditor: AsyncClient, datos: dict[str, Any], codigo: str, filtros: dict[str, str]
) -> None:
    await verificar_paridad(auditor, codigo, filtros)


async def test_actos_declarados(auditor: AsyncClient, datos: dict[str, Any]) -> None:
    todos = await _pantalla(auditor, "ACTOS")
    assert [(f["periodo"], f["escritura"]) for f in todos["filas"]] == [
        ("2026-09", 1),
        ("2026-08", 10),
        ("2026-08", 11),
    ]
    assert {f["categoria"] for f in todos["filas"]} == {"Escritura con valor"}
    # Agosto: todas sus boletas vigentes pagas no (la del adscripto no); septiembre, ninguna.
    assert [f["pago"] for f in todos["filas"]] == ["Pendiente", "Pago parcial", "Pago parcial"]
    assert D(todos["totales"]["base_imponible"]) == D("162345678.91")
    assert D(todos["totales"]["aporte"]) == sum((D(f["aporte"]) for f in todos["filas"]), D(0))

    agosto = await _pantalla(auditor, "ACTOS", periodo_desde="2026-08", periodo_hasta="2026-08")
    assert agosto["total"] == 2
    assert (await _pantalla(auditor, "ACTOS", categoria="ACTA_O_PODER"))["total"] == 0
    assert (await _pantalla(auditor, "ACTOS", naturaleza="compraVENTA"))["total"] == 3
    assert (await _pantalla(auditor, "ACTOS", pago="PENDIENTE"))["total"] == 1


async def test_aportes_por_mes_y_por_anio(auditor: AsyncClient, datos: dict[str, Any]) -> None:
    pagada, pendiente = datos["pagada"], datos["pendiente"]
    por_mes = await _pantalla(auditor, "APORTES_PERIODO")
    filas = {f["periodo"]: f for f in por_mes["filas"]}
    assert list(filas) == ["09/2026", "08/2026"]
    agosto, septiembre = filas["08/2026"], filas["09/2026"]
    # Titular y adscripto: dos boletas vigentes por mes (la anulada no cuenta).
    assert (agosto["boletas"], septiembre["boletas"]) == (2, 2)
    assert D(agosto["pagado"]) == D(pagada["total_a_pagar"])
    assert D(agosto["intereses"]) == D(pagada["interes_mora"])
    assert D(septiembre["pagado"]) == 0
    assert D(septiembre["impago"]) == D(septiembre["declarado"])
    assert D(septiembre["declarado"]) >= D(pendiente["total_en_termino"])
    assert D(agosto["declarado"]) == D(agosto["impago"]) + D(pagada["total_en_termino"])

    por_anio = await _pantalla(auditor, "APORTES_PERIODO", agrupar="ANIO")
    [anio] = por_anio["filas"]
    assert anio["periodo"] == "2026"
    for col in ("boletas", "declarado", "pagado", "intereses", "impago", "con_atraso"):
        assert D(anio[col]) == D(por_mes["totales"][col]), col

    solo_titular = await _pantalla(auditor, "APORTES_PERIODO", escribano="titular")
    assert sum(f["boletas"] for f in solo_titular["filas"]) == 2


async def test_atrasos(
    auditor: AsyncClient, datos: dict[str, Any], hoy_reportes: Callable[[date], None]
) -> None:
    # El 23/10 venció agosto (la del adscripto sigue impaga); septiembre vence el 28/10.
    vencidas = await _pantalla(auditor, "BOLETAS", atraso="VENCIDA_IMPAGA")
    assert [(f["periodo"], f["estado"]) for f in vencidas["filas"]] == [("2026-08", "PENDIENTE")]
    hoy_reportes(date(2026, 11, 1))
    assert (await _pantalla(auditor, "BOLETAS", atraso="VENCIDA_IMPAGA"))["total"] == 3
    con_interes = await _pantalla(auditor, "BOLETAS", atraso="CON_INTERES")
    assert all(D(f["interes_mora"]) > 0 for f in con_interes["filas"])
    # Antes del vencimiento no hay atrasos.
    hoy_reportes(date(2026, 8, 1))
    assert (await _pantalla(auditor, "BOLETAS", atraso="VENCIDA_IMPAGA"))["total"] == 0


async def test_notarios_sin_ddjj_o_sin_pago(
    auditor: AsyncClient,
    datos: dict[str, Any],
    escenario: Escenario,
    hoy_reportes: Callable[[date], None],
) -> None:
    def por_cargo(r: dict[str, Any]) -> dict[str, tuple[str, str]]:
        return {f["cargo"]: (f["ddjj"], f["pago"]) for f in r["filas"]}

    registro = str(escenario.registro.numero_registro)
    # Agosto: el titular pagó; el adscripto debe su boleta.
    agosto = await _pantalla(auditor, "SIN_DDJJ_O_PAGO", periodo="2026-08", registro=registro)
    assert por_cargo(agosto) == {"Adscripto": ("Presentada", "Pendiente de pago")}
    todos = await _pantalla(
        auditor, "SIN_DDJJ_O_PAGO", periodo="2026-08", registro=registro, situacion="TODOS"
    )
    assert por_cargo(todos) == {
        "Titular": ("Presentada", "Pagada"),
        "Adscripto": ("Presentada", "Pendiente de pago"),
    }
    # Julio: nadie presentó.
    julio = await _pantalla(auditor, "SIN_DDJJ_O_PAGO", periodo="2026-07", registro=registro)
    assert por_cargo(julio) == {
        "Titular": ("Sin DDJJ", "Sin boleta"),
        "Adscripto": ("Sin DDJJ", "Sin boleta"),
    }
    assert {f["licencia"] for f in julio["filas"]} == {"—"}
    sin_pago = await _pantalla(
        auditor, "SIN_DDJJ_O_PAGO", periodo="2026-07", registro=registro, situacion="SIN_PAGO"
    )
    assert sin_pago["total"] == 0
    # Sin período: el mes anterior a hoy (23/10/2026 → septiembre).
    defecto = await _pantalla(auditor, "SIN_DDJJ_O_PAGO", registro=registro)
    assert {f["periodo"] for f in defecto["filas"]} == {"2026-09"}
    # Antes de que existiera el cargo, no figura.
    antes = await _pantalla(
        auditor, "SIN_DDJJ_O_PAGO", periodo="2019-12", registro=registro, situacion="TODOS"
    )
    assert antes["total"] == 0


async def test_mis_aportes_solo_las_propias(
    notario: AsyncClient, auditor: AsyncClient, datos: dict[str, Any], escenario: Escenario
) -> None:
    disponibles = [r["codigo"] for r in (await notario.get("/api/v1/reportes")).json()]
    assert disponibles == ["MIS_APORTES"]
    mias = await _pantalla(notario, "MIS_APORTES")
    assert [f["boleta"] for f in mias["filas"]] == [
        datos["pendiente"]["numero"],
        datos["pagada"]["numero"],
    ]
    assert D(mias["totales"]["pagado"]) == D(datos["pagada"]["total_a_pagar"])
    assert D(mias["totales"]["impago"]) == D(datos["pendiente"]["total_en_termino"])
    # El escribano no elige de quién: un parámetro con el id de otro se ignora.
    forzado = await notario.get(
        "/api/v1/reportes/MIS_APORTES",
        params={"_escribano_propio": str(escenario.adscripto.id)},
    )
    assert forzado.json()["total"] == mias["total"]
    septiembre = await _pantalla(notario, "MIS_APORTES", periodo_desde="2026-09")
    assert septiembre["total"] == 1
    exportado = await notario.get("/api/v1/reportes/MIS_APORTES/export", params={"formato": "csv"})
    assert exportado.status_code == 200
    # Los reportes de la Caja siguen cerrados para el escribano.
    assert (await notario.get("/api/v1/reportes/BOLETAS")).status_code == 403
    assert (await notario.get("/api/v1/reportes/SIN_DDJJ_O_PAGO")).status_code == 403
    # Quien no es escribano no tiene «Mis aportes».
    assert (await auditor.get("/api/v1/reportes/MIS_APORTES")).status_code == 403
