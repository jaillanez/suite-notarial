"""Boletas del origen sin registro («a completar») y ajuste de redondeo declarado."""

import csv
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import User
from app.modules.migracion import carga, formato, homologacion, service, valores
from app.modules.migracion.catalog import ModoCorrida, Severidad
from app.modules.migracion.extractor_caja import ajustes_de_redondeo
from app.modules.migracion.models import HistoricoBoleta
from app.modules.migracion.validacion import Existentes, validar
from tests.migracion.conftest import Firmante

Maker = async_sessionmaker[AsyncSession]
URL = "/api/v1/migracion/boletas-sin-registro"


def _editar(
    directorio: Path,
    nombre: str,
    cambio: Callable[[list[dict[str, str]]], None],
    extra: tuple[str, ...] = (),
) -> None:
    ruta = directorio / nombre
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        campos = [
            *(lector.fieldnames or []),
            *[c for c in extra if c not in (lector.fieldnames or [])],
        ]
        filas = list(lector)
    cambio(filas)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";", restval="")
        escritor.writeheader()
        escritor.writerows(filas)


def _sin_registro(directorio: Path, cantidad: int = 3, *, otro_nombre: bool = False) -> list[str]:
    """Deja sin registro las primeras boletas pagadas («P» en el origen), con quien pagó."""
    codigos: list[str] = []

    def cambio(filas: list[dict[str, str]]) -> None:
        for fila in [f for f in filas if f["estado"] == "P"][:cantidad]:
            fila["numero_registro"] = ""
            fila["escribano_origen"] = "PRUEBA Sin Registro"
            codigos.append(fila["codigo_legado"])
        if otro_nombre:
            next(f for f in filas if f["codigo_legado"] == codigos[0])["escribano_origen"] = "OTRO"

    _editar(directorio, "boletas.csv", cambio, extra=("escribano_origen",))
    return codigos


def test_se_valida_con_advertencia(lote: Callable[..., Path]) -> None:
    directorio = lote()
    codigos = _sin_registro(directorio)

    st = validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())

    assert st.bloqueantes() == 0
    avisos = {o.codigo_legado for o in st.observaciones if o.codigo == "REGISTRO_A_COMPLETAR"}
    assert avisos == set(codigos)
    assert all(
        o.severidad is Severidad.ADVERTENCIA
        for o in st.observaciones
        if o.codigo == "REGISTRO_A_COMPLETAR"
    )


def test_sin_registro_ni_nombre_sigue_bloqueando(lote: Callable[..., Path]) -> None:
    directorio = lote()

    def cambio(filas: list[dict[str, str]]) -> None:
        filas[0]["numero_registro"] = ""

    _editar(directorio, "boletas.csv", cambio)
    st = validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())
    assert st.rechazadas["boletas"] == 1


def _control(directorio: Path, entidad: str, importe: str, ajuste: str) -> None:
    def cambio(filas: list[dict[str, str]]) -> None:
        fila = next(f for f in filas if f["entidad"] == entidad)
        fila["importe"], fila["ajuste_redondeo"] = importe, ajuste

    _editar(directorio, "control.csv", cambio, extra=("ajuste_redondeo",))


def _importe_control(directorio: Path, entidad: str) -> Decimal:
    with (directorio / "control.csv").open(encoding="utf-8", newline="") as f:
        fila = next(r for r in csv.DictReader(f, delimiter=";") if r["entidad"] == entidad)
    return valores.importe(fila["importe"])


async def test_ajuste_de_redondeo_declarado_explica_los_centavos(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    # La planilla suma 0,0123 menos que las filas redondeadas: el total declarado da un centavo
    # menos y el ajuste lo explica exacto.
    directorio = lote()
    leido = _importe_control(directorio, "boletas")
    _control(directorio, "boletas", str(leido - Decimal("0.01")), "0.0123")

    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)

    assert r.cuadra is True
    boletas = next(e for e in r.informe["entidades"] if e["entidad"] == "boletas")
    assert boletas["ajuste_redondeo"] == "0.0123"


async def test_un_ajuste_que_no_explica_la_diferencia_no_cuadra(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    directorio = lote()
    leido = _importe_control(directorio, "boletas")
    _control(directorio, "boletas", str(leido - Decimal("0.01")), "0.001")

    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)

    assert r.cuadra is False


def test_ajustes_de_redondeo_del_extractor() -> None:
    redondeos = [
        {"codigo_legado": "APD-1", "original": "10.004", "redondeado": "10.00"},
        {"codigo_legado": "APD-2", "original": "5.005", "redondeado": "5.01"},
        {"codigo_legado": "CRE-3", "original": "1.0049", "redondeado": "1.00"},
    ]
    pagos = [{"codigo_legado": "PAG-2", "boleta": "APD-2"}]

    ajustes = ajustes_de_redondeo(redondeos, pagos)

    assert ajustes == {
        "boletas": Decimal("0.001"),
        "pagos": Decimal("0.005"),
        "creditos": Decimal("-0.0049"),
    }


@pytest.mark.parametrize("ajuste", ["1000", "NaN", "Infinity", "-5000"])
async def test_un_ajuste_desmedido_o_no_finito_no_cuadra(
    maker: Maker, lote: Callable[..., Path], operador: User, ajuste: str
) -> None:
    directorio = lote()
    leido = _importe_control(directorio, "boletas")
    _control(directorio, "boletas", str(leido), ajuste)

    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)

    assert r.cuadra is False
    boletas = next(e for e in r.informe["entidades"] if e["entidad"] == "boletas")
    assert boletas["control_importe_error"]


async def _cargado(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    *,
    otro_nombre: bool = False,
) -> list[str]:
    directorio = lote()
    codigos = _sin_registro(directorio, otro_nombre=otro_nombre)
    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    assert r.cuadra is True
    st = validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)
    await db_session.execute(text("SET LOCAL suite.migracion = 'off'"))
    return codigos


async def test_se_carga_y_la_caja_asigna_el_registro_una_vez(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    caja: Firmante,
) -> None:
    codigos = await _cargado(maker, lote, operador, db_session)
    sin = (await caja.client.get(URL)).json()
    assert sorted(b["codigo_legado"] for b in sin) == sorted(codigos)
    assert {b["escribano_origen"] for b in sin} == {"PRUEBA Sin Registro"}
    assert all(Decimal(b["pagado"]) == Decimal(b["importe"]) for b in sin)

    numero = int(
        (
            await db_session.execute(
                text("SELECT min(numero_registro) FROM padron_registros_notariales")
            )
        ).scalar_one()
    )
    ids = [b["id"] for b in sin]
    inexistente = await caja.client.post(
        f"{URL}/asignacion", json={"boleta_ids": ids, "numero_registro": 99_999}
    )
    assert inexistente.status_code == 422

    response = await caja.client.post(
        f"{URL}/asignacion", json={"boleta_ids": ids[:2], "numero_registro": numero}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"asignadas": 2}
    assert len((await caja.client.get(URL)).json()) == len(ids) - 2
    asignadas = (
        await db_session.scalars(
            select(HistoricoBoleta).where(HistoricoBoleta.codigo_legado.in_(codigos))
        )
    ).all()
    con_registro = [b for b in asignadas if b.registro_id is not None]
    assert len(con_registro) == 2
    assert all(b.registro_asignado_por_user_id == caja.user.id for b in con_registro)
    audit = (
        await db_session.execute(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "MIGRACION_REGISTRO_ASIGNADO"
            )
        )
    ).scalar_one()
    assert audit.new_value == {"registro": numero}
    assert audit.details is not None and len(audit.details["boletas"]) == 2
    # Una vez asignado, no se cambia.
    otra = await caja.client.post(
        f"{URL}/asignacion", json={"boleta_ids": ids[:1], "numero_registro": numero}
    )
    assert otra.status_code == 409


async def test_asignar_requiere_administracion(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    tesoreria: Firmante,
) -> None:
    await _cargado(maker, lote, operador, db_session)
    sin = (await tesoreria.client.get(URL)).json()
    response = await tesoreria.client.post(
        f"{URL}/asignacion", json={"boleta_ids": [sin[0]["id"]], "numero_registro": 1}
    )
    assert response.status_code == 403


async def test_no_mezcla_escribanos_en_una_asignacion(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    caja: Firmante,
) -> None:
    await _cargado(maker, lote, operador, db_session, otro_nombre=True)
    sin = (await caja.client.get(URL)).json()
    assert len({b["escribano_origen"] for b in sin}) == 2

    response = await caja.client.post(
        f"{URL}/asignacion",
        json={"boleta_ids": [b["id"] for b in sin], "numero_registro": 1},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "sentencia",
    [
        # Sin registro, igual no se toca nada más que el registro (y quién y cuándo).
        "UPDATE historico_boletas SET importe = importe + 1 WHERE registro_id IS NULL",
        "UPDATE historico_boletas SET registro_id = (SELECT id FROM padron_registros_notariales "
        "LIMIT 1) WHERE registro_id IS NULL",
        "UPDATE historico_boletas SET registro_id = (SELECT id FROM padron_registros_notariales "
        "LIMIT 1), registro_asignado_por_user_id = (SELECT id FROM security_users LIMIT 1), "
        "registro_asignado_en = now(), periodo = '2001-01' WHERE registro_id IS NULL",
        # Con registro, no se reasigna.
        "UPDATE historico_boletas SET registro_id = NULL, escribano_origen = 'x', "
        "registro_asignado_por_user_id = NULL, registro_asignado_en = NULL "
        "WHERE registro_id IS NOT NULL",
    ],
)
async def test_la_base_solo_admite_la_asignacion(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    sentencia: str,
) -> None:
    await _cargado(maker, lote, operador, db_session)
    with pytest.raises(DBAPIError, match=r"no se modifica|permission"):
        async with db_session.begin_nested():
            await db_session.execute(text(sentencia))
