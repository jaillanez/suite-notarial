"""Corridas contra la base: simulacros, cuadratura, carga definitiva y conformidades."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.audit import AuditSecurityLog
from app.modules.iam.models import User
from app.modules.migracion import service
from app.modules.migracion.catalog import EstadoCorrida, ModoCorrida
from app.modules.migracion.models import (
    Corrida,
    HistoricoBoleta,
    Mapeo,
    ObservacionMigracion,
)
from app.modules.padron.models import Escribano, Persona
from app.modules.prestamos import service as prestamos_service
from tests.migracion.conftest import Firmante

Maker = async_sessionmaker[AsyncSession]


async def _contar(session: AsyncSession, modelo: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(modelo)) or 0)


async def _simulacro(
    maker: Maker, lote: Path, operador: User, homologacion: Path | None = None
) -> service.Resultado:
    return await service.correr(
        lote, ModoCorrida.SIMULACRO, operador.email, homologacion_ruta=homologacion, maker=maker
    )


async def test_simulacro_cuadra_y_no_deja_datos(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    antes = await _contar(db_session, Persona)
    r = await _simulacro(maker, lote(), operador)

    assert r.estado is EstadoCorrida.SIMULADA
    assert r.cuadra is True
    assert r.bloqueantes == 0
    boletas = next(e for e in r.informe["entidades"] if e["entidad"] == "boletas")
    assert boletas["control_importe"] == boletas["importe_leido"] == boletas["importe_cargado"]
    assert boletas["control_filas"] == boletas["leidas"] == boletas["cargadas"]
    assert r.informe["saldos"]["diferencias"] == []
    # Se revirtió todo: ni padrón ni histórico ni mapeo.
    assert await _contar(db_session, Persona) == antes
    assert await _contar(db_session, HistoricoBoleta) == 0
    assert await _contar(db_session, Mapeo) == 0
    corrida = await db_session.get(Corrida, r.corrida_id)
    assert corrida is not None and corrida.estado == "SIMULADA" and corrida.informe is not None


async def test_simulacro_con_defectos_explica_cada_diferencia(
    maker: Maker, lote: Callable[..., Path], operador: User, db_session: AsyncSession
) -> None:
    r = await _simulacro(maker, lote(defectos=True), operador)
    assert r.bloqueantes > 0
    entidades = {e["entidad"]: e for e in r.informe["entidades"]}
    for e in entidades.values():
        # Leídas = cargadas + rechazadas: ninguna fila se pierde sin observación.
        assert e["leidas"] == e["cargadas"] + e["rechazadas"]
        assert e["cuadra_filas"] is True
    # El importe con decimales de un float no se redondea: la cuadratura lo muestra.
    assert entidades["boletas"]["filas_importe_ilegible"] == 1
    assert entidades["boletas"]["cuadra_importe"] is False
    assert r.cuadra is False
    observaciones = (
        await db_session.scalars(
            select(ObservacionMigracion).where(ObservacionMigracion.corrida_id == r.corrida_id)
        )
    ).all()
    assert len(observaciones) == r.bloqueantes + r.advertencias
    # Ningún CUIT ni nombre en las observaciones guardadas.
    assert not any("Sintético" in o.mensaje or "@" in o.mensaje for o in observaciones)


async def test_control_que_no_coincide(
    maker: Maker, lote: Callable[..., Path], operador: User
) -> None:
    directorio = lote()
    control = (directorio / "control.csv").read_text(encoding="utf-8").splitlines()
    # El origen declara 10 escribanos más de los que entregó.
    control = [
        ln.replace("escribanos;", "escribanos;1", 1) if ln.startswith("escribanos;") else ln
        for ln in control
    ]
    (directorio / "control.csv").write_text("\n".join(control) + "\n", encoding="utf-8")
    r = await _simulacro(maker, directorio, operador)
    escribanos = next(e for e in r.informe["entidades"] if e["entidad"] == "escribanos")
    assert escribanos["cuadra_filas"] is False
    assert r.cuadra is False


async def test_operador_sin_permiso(
    maker: Maker, lote: Callable[..., Path], db_session: AsyncSession
) -> None:
    from tests.iam.factories import make_user

    caja = await make_user(db_session, roles=("ROLE_CAJA",))
    with pytest.raises(service.MigracionError, match="migracion:ejecutar"):
        await _simulacro(maker, lote(), caja)


async def test_definitiva_exige_simulacros_conformidad_y_homologacion_aprobada(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    homologacion_aprobada: Path,
    simulacros_minimos: Callable[[int], None],
    tesoreria: Firmante,
    caja: Firmante,
    db_session: AsyncSession,
) -> None:
    simulacros_minimos(2)
    directorio = lote()

    async def definitiva(homologacion: Path | None = homologacion_aprobada) -> service.Resultado:
        return await service.correr(
            directorio,
            ModoCorrida.DEFINITIVA,
            operador.email,
            homologacion_ruta=homologacion,
            maker=maker,
        )

    with pytest.raises(service.MigracionError) as exc:
        await definitiva(None)
    mensaje = str(exc.value)
    assert "homologación es de ejemplo" in mensaje
    assert "Hacen falta 2 simulacros" in mensaje
    assert "No hay un simulacro de este mismo lote" in mensaje

    await _simulacro(maker, directorio, operador, homologacion_aprobada)
    ultimo = await _simulacro(maker, directorio, operador, homologacion_aprobada)
    with pytest.raises(service.MigracionError, match="Falta la conformidad de Tesorería y Caja"):
        await definitiva()

    url = f"/api/v1/migracion/corridas/{ultimo.corrida_id}/conformidad"
    # Cada área firma por la suya y personas distintas.
    ajena = await tesoreria.client.post(url, json={"area": "CAJA"})
    assert ajena.status_code == 403
    firmada = await tesoreria.client.post(url, json={"area": "TESORERIA", "observaciones": "OK"})
    assert firmada.status_code == 200, firmada.text
    assert (await tesoreria.client.post(url, json={"area": "TESORERIA"})).status_code == 409
    detalle = (await caja.client.post(url, json={"area": "CAJA"})).json()
    assert {c["area"] for c in detalle["conformidades"]} == {"TESORERIA", "CAJA"}
    assert detalle["pendiente_para_definitiva"] == []

    r = await definitiva()
    assert r.estado is EstadoCorrida.CARGADA and r.cuadra
    resumen = {e["entidad"]: e for e in r.informe["entidades"]}
    assert await _contar(db_session, HistoricoBoleta) == resumen["boletas"]["cargadas"]
    total = await db_session.scalar(select(func.sum(HistoricoBoleta.importe)))
    assert f"{total:.2f}" == resumen["boletas"]["control_importe"]
    assert await _contar(db_session, Mapeo) > 0

    # Una sola carga definitiva por base.
    with pytest.raises(service.MigracionError, match="ya tiene una carga definitiva"):
        await definitiva()

    eventos = set(
        (
            await db_session.scalars(
                select(AuditSecurityLog.event_type).where(
                    AuditSecurityLog.event_type.like("MIGRACION_%")
                )
            )
        ).all()
    )
    assert {"MIGRACION_INICIADA", "MIGRACION_FINALIZADA", "MIGRACION_CONFORMIDAD"} <= eventos


async def test_no_se_firma_un_simulacro_que_no_cuadro(
    maker: Maker, lote: Callable[..., Path], operador: User, tesoreria: Firmante
) -> None:
    r = await _simulacro(maker, lote(defectos=True), operador)
    respuesta = await tesoreria.client.post(
        f"/api/v1/migracion/corridas/{r.corrida_id}/conformidad", json={"area": "TESORERIA"}
    )
    assert respuesta.status_code == 409
    assert "no cuadró" in respuesta.json()["detail"]


async def test_consulta_y_permisos(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    caja: Firmante,
    notario_cliente: AsyncClient,
) -> None:
    r = await _simulacro(maker, lote(defectos=True), operador)
    lista = (await caja.client.get("/api/v1/migracion/corridas")).json()
    assert [c["id"] for c in lista] == [str(r.corrida_id)]
    detalle = (await caja.client.get(f"/api/v1/migracion/corridas/{r.corrida_id}")).json()
    assert detalle["informe"]["cuadra"] is False
    assert "homologación es de ejemplo" in " ".join(detalle["pendiente_para_definitiva"])

    pagina = (
        await caja.client.get(
            f"/api/v1/migracion/corridas/{r.corrida_id}/observaciones",
            params={"page_size": 5, "severidad": "BLOQUEANTE"},
        )
    ).json()
    assert pagina["total"] == r.bloqueantes
    assert len(pagina["items"]) == 5
    assert all(o["severidad"] == "BLOQUEANTE" for o in pagina["items"])

    assert (await notario_cliente.get("/api/v1/migracion/corridas")).status_code == 403


@pytest.mark.parametrize(
    "sentencia",
    [
        "UPDATE historico_boletas SET importe = importe + 1",
        "DELETE FROM historico_pagos",
        "INSERT INTO historico_boletas (id, corrida_id, codigo_legado, registro_id, periodo, "
        "fecha_emision, fecha_vencimiento, importe, estado) SELECT gen_random_uuid(), corrida_id, "
        "'X-' || codigo_legado, registro_id, periodo, fecha_emision, fecha_vencimiento, 1, "
        "'IMPAGA' FROM historico_boletas LIMIT 1",
        "UPDATE migracion_observaciones SET mensaje = 'otro'",
        "DELETE FROM migracion_mapeo",
        "UPDATE migracion_corridas SET cuadra = true",
        "TRUNCATE migracion_corridas CASCADE",
    ],
)
async def test_inmutable_en_la_base(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    sentencia: str,
) -> None:
    # Datos cargados como en una definitiva (sin pasar por la habilitación).
    from app.modules.migracion import carga, formato, homologacion
    from app.modules.migracion.validacion import Existentes, validar

    r = await _simulacro(maker, lote(defectos=True), operador)
    st = validar(formato.leer_lote(lote("otro")), homologacion.cargar(), Existentes())
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)
    # Fuera de la carga, el histórico ya no acepta nada (SET LOCAL vale para la transacción:
    # se apaga a mano para simular otra sesión).
    await db_session.execute(text("SET LOCAL suite.migracion = 'off'"))
    with pytest.raises(DBAPIError, match=r"no se modifica|no se borra|solo se carga|permission"):
        async with db_session.begin_nested():
            await db_session.execute(text(sentencia))


async def test_deuda_historica_inhabilita_como_garante(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
) -> None:
    from app.modules.migracion import carga, formato, homologacion
    from app.modules.migracion.validacion import Existentes, validar

    r = await _simulacro(maker, lote(), operador)
    st = validar(formato.leer_lote(lote("cargado")), homologacion.cargar(), Existentes())
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)
    impaga = next(b for b in st.boletas if b.estado == "IMPAGA")
    titular = next(
        c for c in st.cargos if c.numero_registro == impaga.numero_registro and c.cargo == "TITULAR"
    )
    escribano = await db_session.scalar(
        select(Escribano).where(Escribano.matricula_numero == titular.matricula)
    )
    assert escribano is not None
    assert not await prestamos_service.deuda_aportes(db_session, escribano.id, impaga.vencimiento)
    despues = date.fromordinal(impaga.vencimiento.toordinal() + 1)
    assert await prestamos_service.deuda_aportes(db_session, escribano.id, despues)


async def test_reporte_de_boletas_historicas(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    auditor: AsyncClient,
) -> None:
    from app.modules.migracion import carga, formato, homologacion
    from app.modules.migracion.validacion import Existentes, validar

    r = await _simulacro(maker, lote(), operador)
    st = validar(formato.leer_lote(lote("cargado")), homologacion.cargar(), Existentes())
    async with db_session.begin_nested():
        await carga.cargar(db_session, st, r.corrida_id, operador.id)

    pantalla = await auditor.get("/api/v1/reportes/BOLETAS_HISTORICAS", params={"page_size": 100})
    assert pantalla.status_code == 200, pantalla.text
    body = pantalla.json()
    assert body["total"] == len(st.boletas)
    emitido = sum((b.importe for b in st.boletas), Decimal(0))
    pagado = sum((p.importe for p in st.pagos), Decimal(0))
    assert Decimal(body["totales"]["importe"]) == emitido
    assert Decimal(body["totales"]["pagado"]) == pagado
    csv = await auditor.get("/api/v1/reportes/BOLETAS_HISTORICAS/export", params={"formato": "csv"})
    assert csv.status_code == 200
    assert csv.text.count("\r\n") == body["total"] + 2


async def test_corrida_fallida_queda_registrada(
    maker: Maker,
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.migracion import carga

    async def rompe(*_: object) -> None:
        raise RuntimeError("corte de luz simulado")

    monkeypatch.setattr(carga, "cargar", rompe)
    with pytest.raises(RuntimeError):
        await _simulacro(maker, lote(), operador)
    corrida = await db_session.scalar(select(Corrida).order_by(Corrida.created_at.desc()))
    assert corrida is not None
    assert corrida.estado == EstadoCorrida.FALLIDA.value
    assert corrida.error is not None and "corte de luz" in corrida.error
    assert await _contar(db_session, HistoricoBoleta) == 0
