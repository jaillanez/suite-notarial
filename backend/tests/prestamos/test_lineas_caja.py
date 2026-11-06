"""Líneas reales de la Caja (Resolución N° 273): datos, cuotas de la planilla y carga."""

import uuid
from datetime import date
from decimal import ROUND_CEILING, Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.common.money import to_money
from app.modules.iam.models import User
from app.modules.prestamos import lineas_caja, motor
from app.modules.prestamos.catalog import Moneda, Sistema
from app.modules.prestamos.lineas_caja import LINEAS_CAJA, PLANILLA_CUOTA_INGRESO
from app.modules.prestamos.models import Linea
from tests.iam.factories import make_user

D = Decimal
POR_CODIGO = {x.codigo: x for x in LINEAS_CAJA}


def test_son_las_ocho_lineas_de_la_planilla() -> None:
    assert list(POR_CODIGO) == list(PLANILLA_CUOTA_INGRESO)
    assert len(LINEAS_CAJA) == 8
    assert {c for c, x in POR_CODIGO.items() if x.moneda is Moneda.USD} == {
        "HIPOTECARIO_USD",
        "HIPOTECARIO_ROTATIVO_USD",
    }
    for x in LINEAS_CAJA:
        assert x.es_ejemplo is False
        assert x.sistema is Sistema.FRANCES
        assert x.afectacion_maxima == D("30")
        assert "Resolución N° 273" in (x.descripcion or "")
    hipotecarias = {c for c, x in POR_CODIGO.items() if x.relacion_capital_hipoteca is not None}
    assert hipotecarias == {
        "HIPOTECARIO",
        "HIPOTECARIO_ROTATIVO",
        "HIPOTECARIO_USD",
        "HIPOTECARIO_ROTATIVO_USD",
    }
    assert POR_CODIGO["PASIVOS"].antiguedad_minima_meses is None
    assert POR_CODIGO["PASIVOS"].requisito_conducta is None
    assert POR_CODIGO["PERSONAL_RAPIDO"].requiere_certificado_ingresos is False
    assert POR_CODIGO["PERSONAL"].requiere_certificado_bienes is True
    # El aviso del tipo de cambio queda a la vista del personal en las líneas en dólares.
    assert "TODO(negocio): definir tipo de cambio" in (
        POR_CODIGO["HIPOTECARIO_USD"].descripcion or ""
    )


@pytest.mark.parametrize("codigo", list(PLANILLA_CUOTA_INGRESO))
def test_el_motor_reproduce_la_cuota_de_la_planilla(codigo: str) -> None:
    """Monto y plazo máximos: la cuota francesa con TNA / 12 es la de la Caja, al centavo."""
    linea = POR_CODIGO[codigo]
    cuota_planilla, ingreso_planilla = (D(v) for v in PLANILLA_CUOTA_INGRESO[codigo])
    cuota = motor.cuota_francesa(linea.monto_maximo, linea.tna, linea.plazo_maximo)
    assert cuota == to_money(cuota_planilla)
    plan = motor.plan(
        Sistema.FRANCES,
        linea.monto_maximo,
        linea.tna,
        linea.plazo_maximo,
        date(2026, 7, 4),
    )
    assert plan[0].cuota == to_money(cuota_planilla)
    assert plan[-1].saldo_final == D("0.00")
    # El ingreso de la planilla es cuota / 0,30 sin redondear. El sistema compara la cuota ya
    # redondeada a centavos, así que el ingreso mínimo que acepta puede diferir en un centavo.
    assert ingreso_planilla * D("0.30") == pytest.approx(cuota_planilla, abs=D("0.000001"))
    minimo = (cuota * 100 / linea.afectacion_maxima).quantize(D("0.01"), rounding=ROUND_CEILING)
    assert abs(minimo - ingreso_planilla) < D("0.02")
    assert motor.afectacion(cuota, minimo) <= linea.afectacion_maxima
    assert motor.afectacion(cuota, minimo - D("0.01")) > linea.afectacion_maxima


async def _operador(db_session: AsyncSession) -> User:
    return await make_user(db_session, roles=("ROLE_CAJA",))


async def _eventos(db_session: AsyncSession, actor: User) -> list[str]:
    return list(
        (
            await db_session.scalars(
                select(AuditSecurityLog.event_type).where(
                    AuditSecurityLog.actor_user_id == actor.id
                )
            )
        ).all()
    )


async def test_carga_idempotente_y_auditada(db_session: AsyncSession) -> None:
    actor = await _operador(db_session)
    ejemplo = Linea(
        id=uuid.uuid4(),
        codigo="LINEA_COMUN_PRUEBA",
        nombre="Línea común (ejemplo)",
        sistema="FRANCES",
        plazo_minimo=6,
        plazo_maximo=36,
        monto_minimo=D("100000.00"),
        monto_maximo=D("5000000.00"),
        tna=D("48.0000"),
        afectacion_maxima=D("30.0000"),
        es_ejemplo=True,
    )
    db_session.add(ejemplo)
    await db_session.flush()
    antes = await db_session.scalar(select(func.count()).select_from(Linea))

    primera = await lineas_caja.cargar(db_session, actor)
    await db_session.commit()

    assert sorted(primera.creadas) == sorted(POR_CODIGO)
    assert "LINEA_COMUN_PRUEBA" in primera.deshabilitadas
    await db_session.refresh(ejemplo)
    assert ejemplo.is_active is False  # baja lógica: la fila sigue
    usd = await db_session.scalar(select(Linea).where(Linea.codigo == "HIPOTECARIO_USD"))
    assert usd is not None
    assert (usd.moneda, usd.tna, usd.monto_maximo) == ("USD", D("7.0000"), D("50000.00"))
    assert usd.relacion_capital_hipoteca == D("70.0000")
    assert (usd.plazo_minimo, usd.monto_minimo) == (1, D("0.01"))
    eventos = await _eventos(db_session, actor)
    assert eventos.count("PRESTAMO_LINEA_CREADA") == 8
    assert eventos.count("PRESTAMO_LINEA_ACTUALIZADA") >= 1

    segunda = await lineas_caja.cargar(db_session, actor)
    await db_session.commit()

    assert segunda.creadas == segunda.actualizadas == segunda.deshabilitadas == []
    assert sorted(segunda.sin_cambios) == sorted(POR_CODIGO)
    assert await _eventos(db_session, actor) == eventos
    despues = await db_session.scalar(select(func.count()).select_from(Linea))
    assert despues == (antes or 0) + 8


async def test_vuelve_a_las_condiciones_de_la_resolucion(db_session: AsyncSession) -> None:
    actor = await _operador(db_session)
    await lineas_caja.cargar(db_session, actor)
    personal = await db_session.scalar(select(Linea).where(Linea.codigo == "PERSONAL"))
    assert personal is not None
    personal.tna = D("40.0000")
    personal.is_active = False
    await db_session.commit()

    resumen = await lineas_caja.cargar(db_session, actor)

    assert resumen.actualizadas == ["PERSONAL"]
    await db_session.refresh(personal)
    assert (personal.tna, personal.is_active) == (D("30.0000"), True)
    logs = (
        await db_session.scalars(
            select(AuditSecurityLog).where(
                AuditSecurityLog.event_type == "PRESTAMO_LINEA_ACTUALIZADA",
                AuditSecurityLog.actor_user_id == actor.id,
            )
        )
    ).all()
    assert [
        (x.old_value, x.new_value) for x in logs if (x.details or {}).get("codigo") == "PERSONAL"
    ] == [({"tna": "40.0000", "is_active": False}, {"tna": "30.0000", "is_active": True})]


async def test_operador_sin_permiso_o_inexistente(db_session: AsyncSession) -> None:
    escribano = await make_user(db_session)
    with pytest.raises(lineas_caja.LineasCajaError, match="prestamos:manage"):
        await lineas_caja.operador(db_session, escribano.email)
    with pytest.raises(lineas_caja.LineasCajaError, match="No hay un usuario activo"):
        await lineas_caja.operador(db_session, "nadie@ejemplo.test")


def test_consola_operador_inexistente(capsys: pytest.CaptureFixture[str]) -> None:
    assert lineas_caja.main(["--operador", "nadie@ejemplo.test", "--simular"]) == 2
    assert "No hay un usuario activo" in capsys.readouterr().err


def test_consola_informa_el_resumen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def falso(email: str, *, simular: bool) -> lineas_caja.Resumen:
        assert (email, simular) == ("caja@ejemplo.test", True)
        return lineas_caja.Resumen(creadas=["PERSONAL"], deshabilitadas=["LINEA_COMUN"])

    monkeypatch.setattr(lineas_caja, "ejecutar", falso)
    assert lineas_caja.main(["--operador", "caja@ejemplo.test", "--simular"]) == 0
    salida = capsys.readouterr().out
    assert "SIMULACIÓN" in salida
    assert "Creadas: 1 (PERSONAL)" in salida
    assert "Líneas de ejemplo deshabilitadas: 1 (LINEA_COMUN)" in salida
