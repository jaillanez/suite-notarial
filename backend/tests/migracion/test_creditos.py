"""Créditos a favor del escribano del sistema anterior (`creditos.csv`, opcional en el v2).

En el libro de pagos de la Caja los importes negativos son créditos a favor del escribano (casi
todos diferencias de inspección). Se migran en positivo a `historico_creditos` y restan del
saldo del registro: boletas no anuladas - pagos - créditos, que puede quedar a favor. Para
habilitar préstamos y garantes los créditos no cuentan (fail-closed, decisión pendiente).
"""

import csv
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.iam.models import User
from app.modules.migracion import carga, cuadratura, formato, homologacion, service
from app.modules.migracion.catalog import Entidad, ModoCorrida, Severidad
from app.modules.migracion.formato import FormatoInvalidoError
from app.modules.migracion.models import HistoricoCredito
from app.modules.migracion.validacion import CERO, BoletaN, Existentes, Staging, validar
from app.modules.padron.models import Escribano, RegistroNotarial
from app.modules.prestamos import service as prestamos_service
from tests.reportes.test_reportes import verificar_paridad

Maker = async_sessionmaker[AsyncSession]
COLUMNAS_CREDITOS = ["codigo_legado", "numero_registro", "fecha", "importe", "periodo", "concepto"]


def _leer(directorio: Path, archivo: str) -> list[dict[str, str]]:
    with (directorio / archivo).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _escribir_creditos(directorio: Path, filas: list[dict[str, str]]) -> None:
    """Reemplaza creditos.csv y su fila de control (como lo declararía el origen)."""
    with (directorio / "creditos.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS_CREDITOS, delimiter=";")
        writer.writeheader()
        writer.writerows(filas)

    def origen(valor: str) -> Decimal:
        # Como lo sumaría el sistema anterior (con decimales de más incluidos).
        return Decimal(valor.replace(".", "").replace(",", ".") if "," in valor else valor)

    total = sum((origen(f["importe"]) for f in filas), Decimal(0))
    control = [f for f in _leer(directorio, "control.csv") if f["entidad"] != "creditos"]
    control.append({"entidad": "creditos", "filas": str(len(filas)), "importe": f"{total:.2f}"})
    with (directorio / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)


def _validar(directorio: Path) -> Staging:
    return validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())


def _saldos_esperados(st: Staging) -> dict[int | None, Decimal]:
    saldo: dict[int | None, Decimal] = defaultdict(lambda: CERO)
    registro_de = {b.codigo: b.numero_registro for b in st.boletas}
    for b in st.boletas:
        saldo[b.numero_registro] += b.importe if b.estado != "ANULADA" else CERO
    for p in st.pagos:
        saldo[registro_de[p.boleta]] -= p.importe
    for c in st.creditos:
        saldo[c.numero_registro] -= c.importe
    return dict(saldo)


# --------------------------------------------------------------------------- formato


def test_el_archivo_es_opcional(lote: Callable[..., Path]) -> None:
    sin = formato.leer_lote(lote("sin", creditos=False))
    con = formato.leer_lote(lote("con"))
    assert Entidad.CREDITOS not in sin.presentes
    assert sin.filas[Entidad.CREDITOS] == []
    assert "creditos" not in sin.control
    assert Entidad.CREDITOS in con.presentes
    assert con.filas[Entidad.CREDITOS]
    # El resto del lote es idéntico: la huella cambia solo por el archivo agregado.
    assert sin.huella != con.huella
    assert _validar(lote("sin2", creditos=False)).creditos == []


def test_archivo_y_control_van_juntos(lote: Callable[..., Path]) -> None:
    sin_control = lote("sin_control")
    control = [f for f in _leer(sin_control, "control.csv") if f["entidad"] != "creditos"]
    with (sin_control / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)
    with pytest.raises(FormatoInvalidoError, match="faltan los totales de creditos"):
        formato.leer_lote(sin_control)

    sin_archivo = lote("sin_archivo")
    (sin_archivo / "creditos.csv").unlink()
    with pytest.raises(FormatoInvalidoError, match="no trae el archivo"):
        formato.leer_lote(sin_archivo)


def test_columnas_obligatorias(lote: Callable[..., Path]) -> None:
    directorio = lote()
    (directorio / "creditos.csv").write_text(
        "codigo_legado;numero_registro;importe\nCRE-1;700;10,00\n", encoding="utf-8"
    )
    with pytest.raises(FormatoInvalidoError, match=r"creditos\.csv: faltan las columnas fecha"):
        formato.leer_lote(directorio)


# --------------------------------------------------------------------------- validación


def test_creditos_validos_se_normalizan(lote: Callable[..., Path]) -> None:
    directorio = lote()
    filas = _leer(directorio, "creditos.csv")
    st = _validar(directorio)
    assert st.observaciones == []
    assert len(st.creditos) == len(filas) > 1
    primero = st.creditos[0]
    assert primero.codigo == filas[0]["codigo_legado"]
    assert primero.importe == Decimal(filas[0]["importe"].replace(",", "."))
    assert primero.importe > 0
    assert primero.periodo is not None and len(primero.periodo) == 7
    assert primero.concepto == "Diferencia de inspección"
    assert st.importe_leido["creditos"] == sum((c.importe for c in st.creditos), CERO)


def test_creditos_invalidos_se_observan(lote: Callable[..., Path]) -> None:
    directorio = lote()
    base = {"numero_registro": "700", "fecha": "2026-05-15", "periodo": "", "concepto": ""}
    _escribir_creditos(
        directorio,
        [
            {**base, "codigo_legado": "CRE-NEG", "importe": "-150,00"},
            {**base, "codigo_legado": "CRE-CERO", "importe": "0"},
            {**base, "codigo_legado": "CRE-FLOAT", "importe": "10.0051"},
            {**base, "codigo_legado": "CRE-REG", "importe": "10,00", "numero_registro": "9999"},
            {**base, "codigo_legado": "CRE-DUP", "importe": "10,00"},
            {**base, "codigo_legado": "CRE-DUP", "importe": "11,00"},
            {**base, "codigo_legado": "CRE-FECHA", "importe": "10,00", "fecha": "31/02/2026"},
            {**base, "codigo_legado": "CRE-PER", "importe": "10,00", "periodo": "2026-13"},
            {**base, "codigo_legado": "CRE-CON", "importe": "10,00", "concepto": "x" * 101},
            {**base, "codigo_legado": "CRE-OK", "importe": "1.234,56"},
        ],
    )
    st = _validar(directorio)
    por_codigo = defaultdict(set)
    for o in st.observaciones:
        assert o.entidad is Entidad.CREDITOS
        assert o.severidad is Severidad.BLOQUEANTE
        por_codigo[o.codigo_legado].add(o.codigo)
    assert por_codigo["CRE-NEG"] == {"IMPORTE_NO_POSITIVO"}
    assert por_codigo["CRE-CERO"] == {"IMPORTE_NO_POSITIVO"}
    assert por_codigo["CRE-FLOAT"] == {"VALOR_INVALIDO"}  # nunca se redondea
    assert por_codigo["CRE-REG"] == {"REGISTRO_NO_MIGRADO"}
    assert por_codigo["CRE-DUP"] == {"CODIGO_DUPLICADO"}
    assert por_codigo["CRE-FECHA"] == {"VALOR_INVALIDO"}
    assert por_codigo["CRE-PER"] == {"VALOR_INVALIDO"}
    assert por_codigo["CRE-CON"] == {"VALOR_INVALIDO"}
    assert "CRE-OK" not in por_codigo
    assert [c.codigo for c in st.creditos] == ["CRE-OK"]
    assert st.creditos[0].importe == Decimal("1234.56")
    assert st.leidas["creditos"] == 10
    assert st.rechazadas["creditos"] == 9
    assert st.importe_ilegible["creditos"] == 1


def test_credito_de_un_registro_rechazado_cae_en_cascada(lote: Callable[..., Path]) -> None:
    st = _validar(lote(defectos=True))
    codigos = {(o.codigo_legado, o.codigo) for o in st.observaciones}
    assert ("CRE-REGISTRO-RECHAZADO", "REGISTRO_NO_MIGRADO") in codigos
    assert ("CRE-EN-CERO", "IMPORTE_NO_POSITIVO") in codigos
    assert {"CRE-REGISTRO-RECHAZADO", "CRE-EN-CERO"}.isdisjoint(c.codigo for c in st.creditos)
    assert st.leidas["creditos"] == len(st.creditos) + st.rechazadas["creditos"]


# --------------------------------------------------------------------------- cuadratura


async def test_simulacro_con_creditos_cuadra(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    directorio = lote()
    st = _validar(directorio)
    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    assert r.cuadra is True, r.informe
    creditos = next(e for e in r.informe["entidades"] if e["entidad"] == "creditos")
    total = f"{sum((c.importe for c in st.creditos), CERO):.2f}"
    assert creditos["control_importe"] == creditos["importe_leido"] == total
    assert creditos["importe_cargado"] == total
    assert creditos["control_filas"] == creditos["leidas"] == creditos["cargadas"]
    assert creditos["cuadra_importe"] is True

    esperado = _saldos_esperados(st)
    saldos = r.informe["saldos"]
    neto = f"{sum(esperado.values(), CERO):.2f}"
    assert saldos["deuda_total_origen"] == saldos["deuda_total_destino"] == neto
    # El sintético deja un registro con saldo a favor.
    a_favor = -sum((v for v in esperado.values() if v < 0), CERO)
    assert a_favor > 0
    assert saldos["registros_a_favor"] == sum(1 for v in esperado.values() if v < 0) >= 1
    assert saldos["a_favor_origen"] == saldos["a_favor_destino"] == f"{a_favor:.2f}"


async def test_lote_sin_creditos_no_los_informa(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    r = await service.correr(
        lote(creditos=False), ModoCorrida.SIMULACRO, operador.email, maker=maker
    )
    assert r.cuadra is True
    assert "creditos" not in {e["entidad"] for e in r.informe["entidades"]}
    assert r.informe["saldos"]["a_favor_origen"] == "0.00"


async def test_control_de_creditos_que_no_coincide(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    directorio = lote()
    control = _leer(directorio, "control.csv")
    for fila in control:
        if fila["entidad"] == "creditos":
            fila["importe"] = str(Decimal(fila["importe"].replace(",", ".")) + Decimal("0.01"))
    with (directorio / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)
    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    creditos = next(e for e in r.informe["entidades"] if e["entidad"] == "creditos")
    assert creditos["cuadra_importe"] is False
    assert r.cuadra is False


async def test_saldos_de_origen_y_destino_restan_los_creditos(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)

    esperado = {k: v.quantize(Decimal("0.01")) for k, v in _saldos_esperados(st).items()}
    assert cuadratura._saldos_origen(st) == esperado
    assert await cuadratura._saldos_destino(db_session, r.corrida_id) == esperado
    # Lo cargado es lo leído, en positivo y con su registro.
    filas = (
        await db_session.scalars(
            select(HistoricoCredito).where(HistoricoCredito.corrida_id == r.corrida_id)
        )
    ).all()
    assert {(c.codigo_legado, c.importe) for c in filas} == {
        (c.codigo, c.importe) for c in st.creditos
    }
    assert all(c.importe > 0 for c in filas)
    registro = await db_session.get(RegistroNotarial, filas[0].registro_id)
    assert registro is not None
    assert cargado.ids[Entidad.CREDITOS][filas[0].codigo_legado] == filas[0].id

    # Si el destino perdiera un crédito, el saldo de ese registro ya no cuadra.
    sin_uno = Staging(boletas=st.boletas, pagos=st.pagos, creditos=st.creditos[1:])
    distinto = cuadratura._saldos_origen(sin_uno)
    numero = st.creditos[0].numero_registro
    assert distinto[numero] == esperado[numero] + st.creditos[0].importe


@pytest.mark.parametrize(
    "sentencia",
    [
        "UPDATE historico_creditos SET importe = importe + 1",
        "DELETE FROM historico_creditos",
        "TRUNCATE historico_creditos",
        "INSERT INTO historico_creditos (id, corrida_id, codigo_legado, registro_id, fecha, "
        "importe) SELECT gen_random_uuid(), corrida_id, 'X-' || codigo_legado, registro_id, "
        "fecha, 1 FROM historico_creditos LIMIT 1",
    ],
)
async def test_historico_de_creditos_inmutable(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    sentencia: str,
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)
    await db_session.execute(text("SET LOCAL suite.migracion = 'off'"))
    with pytest.raises(DBAPIError, match=r"no se modifica|no se borra|solo se carga|permission"):
        async with db_session.begin_nested():
            await db_session.execute(text(sentencia))


async def test_importe_no_positivo_rechazado_por_la_base(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)
    with pytest.raises(DBAPIError, match="ck_historico_creditos_importe"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO historico_creditos (id, corrida_id, codigo_legado, registro_id, "
                    "fecha, importe) SELECT gen_random_uuid(), corrida_id, 'NEG', registro_id, "
                    "fecha, -1 FROM historico_creditos LIMIT 1"
                )
            )


# --------------------------------------------------------------------------- préstamos


def _agregar_pagos(directorio: Path, filas: list[dict[str, str]]) -> None:
    """Agrega pagos a pagos.csv y actualiza su fila de control."""
    pagos = _leer(directorio, "pagos.csv") + filas
    with (directorio / "pagos.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(pagos[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(pagos)
    total = sum((Decimal(p["importe"].replace(",", ".")) for p in pagos), Decimal(0))
    control = _leer(directorio, "control.csv")
    for fila in control:
        if fila["entidad"] == "pagos":
            fila["filas"], fila["importe"] = str(len(pagos)), f"{total:.2f}"
    with (directorio / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["entidad", "filas", "importe"], delimiter=";")
        writer.writeheader()
        writer.writerows(control)


@dataclass
class Caso:
    """Primera boleta impaga de un registro y el día siguiente a su vencimiento (`hoy`)."""

    directorio: Path
    st: Staging
    impaga: BoletaN
    hoy: date


def _caso(lote: Callable[..., Path], nombre: str) -> Caso:
    directorio = lote(nombre)
    st = _validar(directorio)
    impaga = next(b for b in st.boletas if b.estado == "IMPAGA")
    return Caso(directorio, st, impaga, impaga.vencimiento + timedelta(days=1))


async def _cargar(
    maker: Maker, operador: User, db_session: AsyncSession, caso: Caso
) -> tuple[Staging, Escribano, list[uuid.UUID]]:
    r = await service.correr(caso.directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(caso.directorio)
    assert st.bloqueantes() == 0
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)
    numero = caso.impaga.numero_registro
    titular = next(c for c in st.cargos if c.numero_registro == numero and c.cargo == "TITULAR")
    escribano = await db_session.get(Escribano, cargado.ids[Entidad.ESCRIBANOS][titular.escribano])
    assert escribano is not None
    return st, escribano, list(cargado.ids[Entidad.REGISTROS].values())


MOTIVO_DEUDA = "El garante registra deuda de aportes previsionales con la Caja."


async def test_creditos_no_reducen_la_deuda_para_prestamos(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    caso = _caso(lote, "garante")
    numero = caso.impaga.numero_registro
    # Un crédito por más que todo lo que debe el registro: el saldo queda a favor...
    deuda = _saldos_esperados(Staging(boletas=caso.st.boletas, pagos=caso.st.pagos))[numero]
    _escribir_creditos(
        caso.directorio,
        [
            {
                "codigo_legado": "CRE-GRANDE",
                "numero_registro": str(numero),
                "fecha": caso.impaga.vencimiento.isoformat(),
                "importe": f"{deuda + Decimal('5000'):.2f}",
                "periodo": "",
                "concepto": "Diferencia de inspección",
            }
        ],
    )
    st, escribano, _ = await _cargar(maker, operador, db_session, caso)
    assert _saldos_esperados(st)[numero] < 0
    # ...pero para habilitar un garante la deuda vencida sigue (fail-closed, TODO(negocio)).
    assert await prestamos_service.deuda_aportes(db_session, escribano.id, caso.hoy)
    motivos = await prestamos_service.inhabilidades_garante(db_session, escribano, caso.hoy)
    assert MOTIVO_DEUDA in motivos
    # El día del vencimiento todavía no hay deuda vencida.
    assert not await prestamos_service.deuda_aportes(
        db_session, escribano.id, caso.impaga.vencimiento
    )


async def test_pago_de_mas_en_una_boleta_no_tapa_la_deuda_de_otra(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    caso = _caso(lote, "excedente")
    numero = caso.impaga.numero_registro
    pagada = next(
        b
        for b in caso.st.boletas
        if b.numero_registro == numero and b.estado == "PAGADA" and b.vencimiento < caso.hoy
    )
    # Pago de más en la boleta pagada, por todo el importe de la impaga y antes de `hoy`.
    _agregar_pagos(
        caso.directorio,
        [
            {
                "codigo_legado": "PAG-DE-MAS",
                "boleta": pagada.codigo,
                "fecha_pago": pagada.vencimiento.isoformat(),
                "importe": f"{caso.impaga.importe:.2f}",
                "medio": "Transferencia",
            }
        ],
    )
    _, escribano, _ = await _cargar(maker, operador, db_session, caso)
    assert await prestamos_service.deuda_aportes(db_session, escribano.id, caso.hoy)


async def test_pago_con_fecha_posterior_no_cuenta(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    caso = _caso(lote, "posterior")
    despues = caso.hoy + timedelta(days=10)
    _agregar_pagos(
        caso.directorio,
        [
            {
                "codigo_legado": "PAG-POSTERIOR",
                "boleta": caso.impaga.codigo,
                "fecha_pago": despues.isoformat(),
                "importe": f"{caso.impaga.importe:.2f}",
                "medio": "Transferencia",
            }
        ],
    )
    _, escribano, _ = await _cargar(maker, operador, db_session, caso)
    # A `hoy` el pago todavía no existía: hay deuda. Desde su fecha, la boleta está paga.
    assert await prestamos_service.deuda_aportes(db_session, escribano.id, caso.hoy)
    assert not await prestamos_service.deuda_aportes(db_session, escribano.id, despues)


async def test_deuda_historica_por_registro(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    caso = _caso(lote, "registros")
    st, _, registros = await _cargar(maker, operador, db_session, caso)
    lejos = date(2100, 1, 1)
    con_deuda = await prestamos_service.registros_con_deuda_historica(db_session, registros, lejos)
    numeros = dict(
        (
            await db_session.execute(
                select(RegistroNotarial.id, RegistroNotarial.numero_registro).where(
                    RegistroNotarial.id.in_(registros)
                )
            )
        ).all()
    )
    # Con todo vencido, deben exactamente los registros con boletas impagas (con o sin
    # créditos a favor: los créditos no cuentan para habilitar).
    impagos = {b.numero_registro for b in st.boletas if b.estado == "IMPAGA"}
    assert {numeros[r] for r in con_deuda} == impagos
    a_favor = {n for n, v in _saldos_esperados(st).items() if v < 0}
    assert a_favor  # el sintético deja un registro con saldo a favor
    assert {numeros[r] for r in con_deuda} & a_favor == a_favor & impagos


def test_fechas_posteriores_a_la_corrida_se_advierten(lote: Callable[..., Path]) -> None:
    directorio = lote()
    st = validar(
        formato.leer_lote(directorio), homologacion.cargar(), Existentes(), date(2026, 1, 1)
    )
    futuras = [o for o in st.observaciones if o.codigo == "FECHA_POSTERIOR_A_LA_CORRIDA"]
    assert futuras
    assert {o.entidad for o in futuras} == {Entidad.PAGOS, Entidad.CREDITOS}
    assert all(o.severidad is Severidad.ADVERTENCIA for o in futuras)
    # Es una advertencia: las filas se cargan igual.
    assert st.bloqueantes() == 0
    assert len(st.pagos) == st.leidas["pagos"]
    assert len(st.creditos) == st.leidas["creditos"]
    # Con la fecha de hoy (posterior al lote sintético), no hay advertencias.
    assert _validar(directorio).observaciones == []


# --------------------------------------------------------------------------- reporte


async def test_reporte_de_creditos_historicos(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    auditor: AsyncClient,
    notario_cliente: AsyncClient,
) -> None:
    r = await service.correr(lote(), ModoCorrida.SIMULACRO, operador.email, maker=maker)
    st = _validar(lote("cargado"))
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)

    pantalla = await auditor.get("/api/v1/reportes/CREDITOS_HISTORICOS", params={"page_size": 100})
    assert pantalla.status_code == 200, pantalla.text
    body = pantalla.json()
    assert body["total"] == len(st.creditos)
    assert Decimal(body["totales"]["importe"]) == sum((c.importe for c in st.creditos), CERO)
    await verificar_paridad(auditor, "CREDITOS_HISTORICOS", {})

    primero = st.creditos[0]
    filtrado = (
        await auditor.get(
            "/api/v1/reportes/CREDITOS_HISTORICOS",
            params={"registro": str(primero.numero_registro)},
        )
    ).json()
    assert filtrado["total"] == sum(
        1 for c in st.creditos if c.numero_registro == primero.numero_registro
    )
    await verificar_paridad(
        auditor, "CREDITOS_HISTORICOS", {"registro": str(primero.numero_registro)}
    )
    assert primero.periodo is not None
    por_periodo = (
        await auditor.get(
            "/api/v1/reportes/CREDITOS_HISTORICOS",
            params={"periodo_desde": primero.periodo, "periodo_hasta": primero.periodo},
        )
    ).json()
    assert por_periodo["total"] == sum(1 for c in st.creditos if c.periodo == primero.periodo)
    por_fecha = (
        await auditor.get(
            "/api/v1/reportes/CREDITOS_HISTORICOS",
            params={
                "fecha_desde": primero.fecha.isoformat(),
                "fecha_hasta": primero.fecha.isoformat(),
            },
        )
    ).json()
    assert por_fecha["total"] == sum(1 for c in st.creditos if c.fecha == primero.fecha)

    assert (await notario_cliente.get("/api/v1/reportes/CREDITOS_HISTORICOS")).status_code == 403
    assert (
        await notario_cliente.get("/api/v1/reportes/CREDITOS_HISTORICOS/export")
    ).status_code == 403
