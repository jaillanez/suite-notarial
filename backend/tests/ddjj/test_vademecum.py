"""Vademécum de aportes 2026, precio y avalúo, y el criterio de pluralidad de actos.

Casos del documento de la Caja (vigencia junio 2026): venta 0,40 % con mínimo 57.289; donación
fijo mayor 37.446; poder fijo menor 9.922; hipoteca del IPV exenta. Con varios actos y las
mismas partes aporta solo el de mayor valor; con partes distintas, cada uno.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ddjj import vademecum_caja
from app.modules.ddjj.catalog import CategoriaActo
from app.modules.ddjj.liquidacion import ActoALiquidar, AporteActo, aplicar_pluralidad
from app.modules.ddjj.models import Acto, VademecumActo
from app.modules.ddjj.schemas import ActoIn
from app.modules.parametros import service as parametros
from app.modules.parametros.catalog import CriterioPluralidad, ReglaRedondeo, TipoConcepto
from app.modules.parametros.motor import VigenciaSnapshot
from tests.ddjj.conftest import Escenario
from tests.ddjj.test_protocolo import _agregar, _borrador
from tests.iam.factories import make_user

D = Decimal
VENTA = D("57289.00")  # mínimo de una escritura con valor desde junio 2026
DONACION = D("37446.00")  # fijo mayor
PODER = D("9922.00")  # fijo menor


def criterio(c: CriterioPluralidad) -> VigenciaSnapshot:
    return VigenciaSnapshot(
        vigencia_id=uuid.uuid4(),
        concepto_codigo="CRITERIO_PLURALIDAD_ACTOS",
        tipo=TipoConcepto.CRITERIO_PLURALIDAD,
        fecha_desde=date(2026, 6, 1),
        fecha_hasta=None,
        porcentaje=None,
        monto_fijo=None,
        monto_minimo=None,
        monto_maximo=None,
        tasa=None,
        periodo_tasa=None,
        dias_gracia=None,
        regla_redondeo=ReglaRedondeo.HALF_UP,
        criterio=c,
    )


def acto(categoria: CategoriaActo, numero: int = 1, *, mismas_partes: bool = True) -> ActoALiquidar:
    base = D("1000000") if categoria is CategoriaActo.ESCRITURA_CON_VALOR else D("0")
    return ActoALiquidar(categoria, base, ("GENERAL", numero), mismas_partes)


def aportes(*montos: Decimal) -> list[AporteActo]:
    return [AporteActo(m, None) for m in montos]


V, MAYOR, MENOR = (
    CategoriaActo.ESCRITURA_CON_VALOR,
    CategoriaActo.OTRO_ACTO,
    CategoriaActo.ACTA_O_PODER,
)


# --------------------------------------------------------------------------- regla pura


def test_solo_el_mayor_con_las_mismas_partes() -> None:
    actos = [acto(V), acto(MAYOR), acto(MENOR)]
    out = aplicar_pluralidad(
        actos, aportes(VENTA, DONACION, PODER), criterio(CriterioPluralidad.SOLO_EL_MAYOR)
    )
    assert [a.aporte for a in out] == [VENTA, D("0.00"), D("0.00")]
    assert [a.aporte_individual for a in out] == [VENTA, DONACION, PODER]
    assert [a.incluido_en_otro for a in out] == [False, True, True]


def test_el_mayor_es_el_que_mas_aporta_y_el_empate_lo_gana_el_primero() -> None:
    # Una donación aporta más que un poder aunque esté después.
    out = aplicar_pluralidad(
        [acto(MENOR), acto(MAYOR), acto(MAYOR)],
        aportes(PODER, DONACION, DONACION),
        criterio(CriterioPluralidad.SOLO_EL_MAYOR),
    )
    assert [a.aporte for a in out] == [D("0.00"), DONACION, D("0.00")]


def test_suman_todos() -> None:
    out = aplicar_pluralidad(
        [acto(V), acto(MAYOR)], aportes(VENTA, DONACION), criterio(CriterioPluralidad.SUMAN_TODOS)
    )
    assert [a.aporte for a in out] == [VENTA, DONACION]
    assert not any(a.incluido_en_otro for a in out)


def test_variables_suman_y_el_fijo_una_vez() -> None:
    out = aplicar_pluralidad(
        [acto(V), acto(V), acto(MENOR), acto(MAYOR)],
        aportes(VENTA, VENTA, PODER, DONACION),
        criterio(CriterioPluralidad.VARIABLES_SUMAN_FIJO_UNA_VEZ),
    )
    assert [a.aporte for a in out] == [VENTA, VENTA, D("0.00"), DONACION]


def test_partes_distintas_aporta_cada_uno() -> None:
    out = aplicar_pluralidad(
        [acto(V, mismas_partes=False), acto(V, mismas_partes=False)],
        aportes(VENTA, VENTA),
        criterio(CriterioPluralidad.SOLO_EL_MAYOR),
    )
    assert [a.aporte for a in out] == [VENTA, VENTA]


def test_solo_agrupa_actos_de_la_misma_escritura() -> None:
    out = aplicar_pluralidad(
        [acto(V, 1), acto(MAYOR, 2)],
        aportes(VENTA, DONACION),
        criterio(CriterioPluralidad.SOLO_EL_MAYOR),
    )
    assert [a.aporte for a in out] == [VENTA, DONACION]


def test_sin_criterio_vigente_aporta_cada_uno() -> None:
    out = aplicar_pluralidad([acto(V), acto(MAYOR)], aportes(VENTA, DONACION), None)
    assert [a.aporte for a in out] == [VENTA, DONACION]


def test_la_base_es_el_mayor_de_precio_y_avaluo() -> None:
    datos: dict[str, Any] = {
        "escribano_id": uuid.uuid4(),
        "numero_escritura": 1,
        "fecha_acto": date(2026, 9, 1),
        "naturaleza": "Venta",
        "categoria": "ESCRITURA_CON_VALOR",
    }
    assert ActoIn(**datos, precio=D("100"), avaluo=D("250")).base_imponible == D("250")
    assert ActoIn(**datos, precio=D("300")).base_imponible == D("300")
    with pytest.raises(ValueError, match="aporte variable"):
        ActoIn(**{**datos, "categoria": "OTRO_ACTO"}, precio=D("100"))


# --------------------------------------------------------------------------- con la API


@pytest.fixture
async def vademecum(db_session: AsyncSession, escenario: Escenario) -> dict[str, VademecumActo]:
    """El vademécum 2026 cargado y el criterio del documento aprobado por otra persona."""
    autor = await make_user(db_session, roles=("ROLE_ADMIN",))
    aprobador = await make_user(db_session, roles=("ROLE_ADMIN",))
    resumen = await vademecum_caja.cargar(db_session, autor)
    assert resumen.propuesta_id is not None
    await parametros.aprobar_vigencia(
        db_session, vademecum_caja.CONSOLA, aprobador, resumen.propuesta_id
    )
    filas = (await db_session.execute(select(VademecumActo))).scalars().all()
    return {f.codigo: f for f in filas}


def _del_vademecum(e: Escenario, item: VademecumActo, numero: int, **extra: Any) -> dict[str, Any]:
    return {
        "escribano_id": str(e.titular.id),
        "numero_escritura": numero,
        "fecha_acto": "2026-09-15",
        "naturaleza": item.nombre,
        "categoria": item.categoria,
        "motivo_exencion": item.motivo_exencion,
        "vademecum_id": str(item.id),
        **extra,
    }


async def test_carga_del_vademecum_2026(vademecum: dict[str, VademecumActo]) -> None:
    assert len(vademecum) == 34
    assert vademecum["VENTA"].categoria == "ESCRITURA_CON_VALOR"
    assert vademecum["ACTA_LABORAL"].categoria == "OTRO_ACTO"
    assert vademecum["ACTA"].categoria == "ACTA_O_PODER"
    assert vademecum["IPV"].motivo_exencion == "CONVENIO_IPV"
    # Ninguna letra cirílica del documento original.
    assert not any("Ѐ" <= c <= "ӿ" for f in vademecum.values() for c in f.nombre)


async def test_vademecum_vigente_por_fecha(
    notario: AsyncClient, vademecum: dict[str, VademecumActo]
) -> None:
    junio = await notario.get("/api/v1/ddjj/vademecum", params={"fecha": "2026-06-01"})
    assert junio.status_code == 200
    assert [a["codigo"] for a in junio.json()][:2] == ["VENTA", "CESION_ONEROSA_INMUEBLE"]
    mayo = await notario.get("/api/v1/ddjj/vademecum", params={"fecha": "2026-05-31"})
    assert mayo.json() == []


async def test_acto_del_vademecum_con_precio_y_avaluo(
    notario: AsyncClient, escenario: Escenario, vademecum: dict[str, VademecumActo]
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    venta = _del_vademecum(
        escenario, vademecum["VENTA"], 1, precio="20000000.00", avaluo="25000000.00"
    )
    creado = await _agregar(notario, ddjj["id"], venta)
    assert creado.status_code == 201, creado.text
    body = creado.json()
    assert body["base_imponible"] == "25000000.00"
    assert body["vademecum_nombre"] == "Venta"
    assert body["fuera_de_vademecum"] is False

    # La categoría la fija el vademécum: el servidor no acepta otra.
    trucho = _del_vademecum(escenario, vademecum["DONACION"], 2, categoria="ACTA_O_PODER")
    rechazo = await _agregar(notario, ddjj["id"], trucho)
    assert rechazo.status_code == 422
    assert "vademécum" in rechazo.json()["detail"]

    # Sin vademécum queda marcado para que lo revise la Caja.
    libre = {
        "escribano_id": str(escenario.titular.id),
        "numero_escritura": 3,
        "fecha_acto": "2026-09-15",
        "naturaleza": "Acto raro",
        "categoria": "OTRO_ACTO",
    }
    marcado = await _agregar(notario, ddjj["id"], libre)
    assert marcado.status_code == 201, marcado.text
    assert marcado.json()["fuera_de_vademecum"] is True


async def test_acto_del_vademecum_de_otro_periodo_se_rechaza(
    notario: AsyncClient, escenario: Escenario, vademecum: dict[str, VademecumActo]
) -> None:
    mayo = await _borrador(notario, escenario, "2026-05")
    venta = _del_vademecum(
        escenario, vademecum["VENTA"], 1, fecha_acto="2026-05-10", precio="1000000.00"
    )
    response = await _agregar(notario, mayo["id"], venta)
    assert response.status_code == 422
    assert "no rige" in response.json()["detail"]


async def test_pluralidad_en_la_liquidacion_y_al_presentar(
    notario: AsyncClient,
    escenario: Escenario,
    vademecum: dict[str, VademecumActo],
    db_session: AsyncSession,
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    venta = _del_vademecum(escenario, vademecum["VENTA"], 10, precio="1000000.00")
    assert (await _agregar(notario, ddjj["id"], venta)).status_code == 201
    donacion = _del_vademecum(
        escenario, vademecum["DONACION"], 10, acto_multiple=True, mismas_partes=True
    )
    assert (await _agregar(notario, ddjj["id"], donacion)).status_code == 201
    # Otra escritura con dos ventas entre partes distintas: aporta cada una.
    for _ in range(2):
        otra = _del_vademecum(
            escenario,
            vademecum["VENTA"],
            11,
            precio="1000000.00",
            acto_multiple=_ > 0,
            mismas_partes=False,
        )
        assert (await _agregar(notario, ddjj["id"], otra)).status_code == 201

    liq = (
        await notario.get(
            f"/api/v1/ddjj/declaraciones/{ddjj['id']}/liquidacion",
            params={"fecha_pago": "2026-10-23"},
        )
    ).json()
    assert liq["criterio_pluralidad"] == "SOLO_EL_MAYOR"
    assert [(a["aporte"], a["incluido_en_otro"]) for a in liq["aportes"]] == [
        ("57289.00", False),
        ("0.00", True),
        ("57289.00", False),
        ("57289.00", False),
    ]
    assert liq["aportes"][1]["aporte_individual"] == "37446.00"
    assert liq["total_protocolos"] == "171867.00"

    presentada = await notario.post(
        f"/api/v1/ddjj/declaraciones/{ddjj['id']}/presentar", json={"fecha_pago": "2026-10-23"}
    )
    assert presentada.status_code == 201, presentada.text
    congelados = (
        (
            await db_session.execute(
                select(Acto)
                .where(Acto.ddjj_id == uuid.UUID(ddjj["id"]))
                .order_by(Acto.numero_escritura, Acto.orden_en_escritura)
            )
        )
        .scalars()
        .all()
    )
    assert [(a.aporte, a.aporte_individual) for a in congelados] == [
        (D("57289.00"), D("57289.00")),
        (D("0.00"), D("37446.00")),
        (D("57289.00"), D("57289.00")),
        (D("57289.00"), D("57289.00")),
    ]
    assert congelados[0].vigencia_pluralidad_id is not None
    assert congelados[2].vigencia_pluralidad_id is None

    # La rectificativa conserva el vademécum, el precio y las partes.
    rect = (await notario.post(f"/api/v1/ddjj/declaraciones/{ddjj['id']}/rectificar")).json()
    assert [a["vademecum_nombre"] for a in rect["actos"]][:2] == [
        "Venta",
        "Donación - aceptación de compra y/o venta",
    ]
    assert [a["mismas_partes"] for a in rect["actos"]] == [True, True, False, False]


async def test_la_respuesta_de_las_partes_rige_para_toda_la_escritura(
    notario: AsyncClient, escenario: Escenario, vademecum: dict[str, VademecumActo]
) -> None:
    ddjj = await _borrador(notario, escenario, "2026-09")
    venta = _del_vademecum(escenario, vademecum["VENTA"], 20, precio="1000000.00")
    assert (await _agregar(notario, ddjj["id"], venta)).status_code == 201
    poder = _del_vademecum(
        escenario, vademecum["PODER"], 20, acto_multiple=True, mismas_partes=False
    )
    assert (await _agregar(notario, ddjj["id"], poder)).status_code == 201
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{ddjj['id']}")).json()
    assert [a["mismas_partes"] for a in detalle["actos"]] == [False, False]


# --------------------------------------------------------------------------- administración


async def test_version_nueva_cierra_la_anterior_y_queda_auditada(
    staff: AsyncClient,
    app: Any,
    db_session: AsyncSession,
    vademecum: dict[str, VademecumActo],
) -> None:
    from tests.ddjj.conftest import _client
    from tests.iam.test_rbac import login

    admin = await make_user(db_session, roles=("ROLE_ADMIN",), totp_secret="JBSWY3DPEHPK3PXP")
    async with await _client(app) as ac:
        await login(ac, admin, "JBSWY3DPEHPK3PXP")
        nueva = {
            "codigo": "TESTAMENTO",
            "nombre": "Testamento",
            "categoria": "ACTA_O_PODER",
            "fecha_desde": "2027-01-01",
            "resolucion": "Asamblea de prueba",
            "motivo": "Cambio de política de prueba",
        }
        creada = await ac.post("/api/v1/ddjj/vademecum", json=nueva)
        assert creada.status_code == 201, creada.text
        assert creada.json()["version"] == 2
        # No puede empezar antes ni junto con una versión que ya empezó.
        repetida = await ac.post("/api/v1/ddjj/vademecum", json=nueva)
        assert repetida.status_code == 409

        baja = await ac.post(
            f"/api/v1/ddjj/vademecum/{creada.json()['id']}/baja",
            json={"desde": "2027-06-01", "motivo": "Deja de figurar en el vademécum"},
        )
        assert baja.status_code == 200, baja.text
        assert baja.json()["fecha_hasta"] == "2027-05-31"

    anterior = await db_session.get(VademecumActo, vademecum["TESTAMENTO"].id)
    await db_session.refresh(anterior)
    assert anterior is not None and anterior.fecha_hasta == date(2026, 12, 31)
    eventos = (
        await db_session.execute(
            text(
                "SELECT event_type FROM audit_security_logs "
                "WHERE event_type LIKE 'VADEMECUM_%' AND actor_user_id = :id"
            ),
            {"id": admin.id},
        )
    ).scalars()
    assert sorted(eventos) == [
        "VADEMECUM_ACTO_AGREGADO",
        "VADEMECUM_ACTO_CERRADO",
        "VADEMECUM_ACTO_CERRADO",
    ]


async def test_solo_quien_administra_parametros_edita_el_vademecum(
    notario: AsyncClient, staff: AsyncClient, vademecum: dict[str, VademecumActo]
) -> None:
    nueva = {
        "codigo": "NUEVO_ACTO",
        "nombre": "Nuevo acto",
        "categoria": "OTRO_ACTO",
        "fecha_desde": "2027-01-01",
        "resolucion": "Asamblea de prueba",
        "motivo": "Intento sin permiso",
    }
    assert (await notario.post("/api/v1/ddjj/vademecum", json=nueva)).status_code == 403
    assert (await staff.post("/api/v1/ddjj/vademecum", json=nueva)).status_code == 403
    assert (await notario.get("/api/v1/ddjj/vademecum/historial")).status_code == 403


async def test_una_version_no_se_modifica_ni_se_borra(
    db_session: AsyncSession, vademecum: dict[str, VademecumActo]
) -> None:
    venta = vademecum["VENTA"].id
    for sentencia in (
        "UPDATE ddjj_vademecum SET categoria = 'OTRO_ACTO' WHERE id = :id",
        "DELETE FROM ddjj_vademecum WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sentencia), {"id": venta})
        await db_session.rollback()


async def test_el_criterio_de_una_vigencia_no_se_modifica(
    db_session: AsyncSession, vademecum: dict[str, VademecumActo]
) -> None:
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "UPDATE parametros_vigencias SET criterio = 'SUMAN_TODOS' "
                "WHERE criterio IS NOT NULL"
            )
        )
    await db_session.rollback()


async def test_un_criterio_no_lleva_montos(
    db_session: AsyncSession, vademecum: dict[str, VademecumActo]
) -> None:
    from app.core.errors import ProblemError
    from app.modules.parametros.models import Concepto
    from app.modules.parametros.schemas import VigenciaIn

    concepto = await db_session.scalar(
        select(Concepto).where(Concepto.codigo == "CRITERIO_PLURALIDAD_ACTOS")
    )
    assert concepto is not None
    actor = await make_user(db_session, roles=("ROLE_ADMIN",))
    for datos in (
        {"monto_fijo": D("10")},  # sin criterio y con un monto
        {"criterio": CriterioPluralidad.SUMAN_TODOS, "porcentaje": D("1")},
    ):
        with pytest.raises(ProblemError):
            await parametros.proponer_vigencia(
                db_session,
                vademecum_caja.CONSOLA,
                actor,
                concepto.id,
                VigenciaIn(
                    fecha_desde=date(2027, 1, 1),
                    resolucion_respaldo="Prueba",
                    motivo="Valores incompatibles",
                    **datos,
                ),
            )
