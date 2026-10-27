"""Interés por tramos: un cambio de tasa durante la mora se aplica desde el día en que rige."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.parametros.models import Concepto, Vigencia
from tests.ddjj.conftest import Escenario
from tests.ddjj.test_flujo import _cargar_1069, _presentar, _solo_titular

D = Decimal


async def _nueva_tasa(db_session: AsyncSession, desde: date, tasa: str) -> None:
    """Cierra la tasa de mora abierta el día anterior y abre otra (5 % mensual)."""
    concepto_id = await db_session.scalar(
        select(Concepto.id).where(Concepto.codigo == "TASA_INTERES_MORA")
    )
    abierta = await db_session.scalar(
        select(Vigencia).where(Vigencia.concepto_id == concepto_id, Vigencia.fecha_hasta.is_(None))
    )
    assert abierta is not None
    abierta.fecha_hasta = date.fromordinal(desde.toordinal() - 1)
    await db_session.flush()
    db_session.add(
        Vigencia(
            concepto_id=concepto_id,
            version=99,
            fecha_desde=desde,
            tasa=D(tasa),
            periodo_tasa="MENSUAL",
            dias_gracia=0,
            estado="VIGENTE",
            resolucion_respaldo="Prueba",
            motivo="Cambio de tasa",
            created_by_user_id=abierta.created_by_user_id,
            aprobado_por_user_id=abierta.aprobado_por_user_id,
        )
    )
    await db_session.commit()


async def test_boleta_con_cambio_de_tasa_durante_la_mora(
    notario: AsyncClient, client: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    await _solo_titular(db_session, escenario)
    ddjj = await _cargar_1069(notario, escenario)
    original = await _presentar(notario, ddjj["id"])
    assert original["tramos_mora"] == []  # en término
    await _nueva_tasa(db_session, date(2026, 11, 3), "5.0000")

    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/boletas"
    boleta = (await notario.post(url, json={"fecha_pago": "2026-11-07"})).json()

    # Vence el 28/10: 5 días al 4,25 % mensual (29/10 a 02/11) y 5 al 5 % (03/11 a 07/11).
    total = D("1081699.06")
    exactos = [total * D("4.25") / 100 / 30 * 5, total * D("5") / 100 / 30 * 5]
    interes = sum(exactos, D(0)).quantize(D("0.01"))
    assert boleta["dias_mora"] == 10
    assert boleta["interes_mora"] == f"{interes:.2f}" == "16676.19"
    assert boleta["tramos_mora"] == [
        {
            "desde": "2026-10-29",
            "hasta": "2026-11-02",
            "dias": 5,
            "tasa": "4.2500",
            "periodo_tasa": "MENSUAL",
            "interes": "7662.04",
        },
        {
            "desde": "2026-11-03",
            "hasta": "2026-11-07",
            "dias": 5,
            "tasa": "5.0000",
            "periodo_tasa": "MENSUAL",
            # 9.014,16 por separado: el último tramo absorbe el redondeo del total.
            "interes": "9014.15",
        },
    ]
    assert D(boleta["total_a_pagar"]) == total + interes

    # La huella cubre el detalle y la boleta sigue verificando como íntegra.
    verificacion = (
        await client.get(f"/api/v1/boletas/verificar/{boleta['codigo_verificacion']}")
    ).json()
    assert verificacion["integra"] is True
    pdf = await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}/pdf")
    assert pdf.status_code == 200

    # La vista previa calcula igual.
    preview = (
        await notario.get(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion",
            params={"fecha_pago": "2026-11-07"},
        )
    ).json()
    assert preview["interes_mora"] == "16676.19"
    assert [t["interes"] for t in preview["tramos_mora"]] == ["7662.04", "9014.15"]


async def test_el_detalle_de_la_mora_no_se_modifica(
    notario: AsyncClient, escenario: Escenario, db_session: AsyncSession
) -> None:
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    from app.modules.ddjj.models import BoletaTramoMora

    await _solo_titular(db_session, escenario)
    ddjj = await _cargar_1069(notario, escenario)
    await _presentar(notario, ddjj["id"])
    url = f"/api/v1/ddjj/declaraciones/{ddjj['id']}/boletas"
    assert (await notario.post(url, json={"fecha_pago": "2026-11-07"})).status_code == 201

    try:
        await db_session.execute(update(BoletaTramoMora).values(interes=D("1.00")))
        await db_session.flush()
    except DBAPIError as exc:
        assert "inmutable" in str(exc)
        await db_session.rollback()
    else:
        raise AssertionError("El detalle de la mora se pudo modificar")
