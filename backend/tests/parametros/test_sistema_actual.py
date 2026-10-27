"""Los parámetros relevados del sistema actual son coherentes y reproducen sus resultados."""

import itertools
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.parametros import motor, service
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.parametros.sistema_actual import CONCEPTOS, VENCIMIENTOS_2026
from tests.iam.factories import make_user


def test_tramos_contiguos_sin_superposicion() -> None:
    for concepto in CONCEPTOS:
        tramos = concepto.tramos
        assert tramos, concepto.codigo
        assert tramos[-1].hasta is None, f"{concepto.codigo}: el último tramo queda abierto"
        for actual, siguiente in itertools.pairwise(tramos):
            assert actual.hasta is not None
            assert actual.hasta + timedelta(days=1) == siguiente.desde, concepto.codigo


async def _cargar(db_session: AsyncSession) -> None:
    autor = await make_user(db_session, roles=("ROLE_ADMIN",))
    aprobador = await make_user(db_session, roles=("ROLE_ADMIN",))
    for relevado in CONCEPTOS:
        concepto = Concepto(
            id=uuid.uuid4(),
            codigo=relevado.codigo,
            nombre=relevado.nombre,
            tipo=relevado.tipo.value,
        )
        db_session.add(concepto)
        for version, tramo in enumerate(relevado.tramos, start=1):
            db_session.add(
                Vigencia(
                    concepto_id=concepto.id,
                    version=version,
                    fecha_desde=tramo.desde,
                    fecha_hasta=tramo.hasta,
                    **tramo.valores,
                    estado="VIGENTE",
                    resolucion_respaldo="Sistema actual",
                    motivo="Prueba de carga",
                    created_by_user_id=autor.id,
                    aprobado_por_user_id=aprobador.id,
                )
            )
    await db_session.commit()


async def test_reproduce_reporte_y_boleta_del_sistema_actual(db_session: AsyncSession) -> None:
    await _cargar(db_session)  # la base acepta todos los tramos (sin solapamiento)
    agosto = date(2026, 8, 1)
    setiembre = date(2026, 9, 1)

    escritura = await service.get_vigencia(db_session, "APORTE_ESCRITURA", agosto)
    # Reporte mensual 08/2026: VENTA con base 3.566.100 -> aporte 57.289 (rige el mínimo).
    assert motor.aporte_porcentual(Decimal("3566100"), escritura) == Decimal("57289.00")
    # 0,40 % de 20.000.000 = 80.000 (entre mínimo y tope).
    assert motor.aporte_porcentual(Decimal("20000000"), escritura) == Decimal("80000.00")
    # Tope del período.
    assert motor.aporte_porcentual(Decimal("2000000000"), escritura) == Decimal("3482672.00")

    poderes = await service.get_vigencia(db_session, "APORTE_FIJO_ACTAS_PODERES", agosto)
    otros = await service.get_vigencia(db_session, "APORTE_FIJO_OTROS_ACTOS", agosto)
    assert motor.aporte_fijo(poderes) == Decimal("9922.00")
    assert motor.aporte_fijo(otros) == Decimal("37446.00")

    # Boleta 09/2026: aporte mínimo 85.932 y médico 97.000.
    minimo = await service.get_vigencia(db_session, "APORTE_MINIMO_MENSUAL", setiembre)
    medico = await service.get_vigencia(db_session, "APORTE_MEDICO_ASISTENCIAL", setiembre)
    assert motor.aporte_fijo(minimo) == Decimal("85932.00")
    assert motor.aporte_fijo(medico) == Decimal("97000.00")
    total_protocolos = Decimal("984699.06")
    assert total_protocolos - motor.aporte_fijo(minimo) == Decimal("898767.06")  # excedente
    assert total_protocolos + motor.aporte_fijo(medico) == Decimal("1081699.06")  # total

    # Primer semestre: valores anteriores.
    marzo = await service.get_vigencia(db_session, "APORTE_ESCRITURA", date(2026, 3, 15))
    assert marzo.monto_minimo == Decimal("52081.00")
    assert VENCIMIENTOS_2026[9] == date(2026, 10, 28)


async def test_reproduce_la_mora_de_la_boleta_sin_actos_01_2026(db_session: AsyncSession) -> None:
    """Boleta sin actos 01/2026 del sistema actual (registro 111), pagada el 27/10/2026:
    total en término 154.120,00, vencimiento 02/03/2026, 239 días, interés 52.182,46.
    Tasa confirmada por la Caja: 4,25 % mensual, interés simple, mes de 30 días."""
    await _cargar(db_session)
    enero = date(2026, 1, 1)
    minimo = await service.get_vigencia(db_session, "APORTE_MINIMO_MENSUAL", enero)
    medico = await service.get_vigencia(db_session, "APORTE_MEDICO_ASISTENCIAL", enero)
    total_en_termino = motor.aporte_fijo(minimo) + motor.aporte_fijo(medico)
    assert total_en_termino == Decimal("154120.00")

    vencimiento = VENCIMIENTOS_2026[1]
    assert vencimiento == date(2026, 3, 2)
    mora = await service.get_vigencia(db_session, "TASA_INTERES_MORA", vencimiento)
    dias = motor.dias_de_mora(vencimiento, date(2026, 10, 27), mora)
    assert dias == 239
    interes = motor.interes_mora(total_en_termino, dias, mora)
    assert interes == Decimal("52182.46")
    assert total_en_termino + interes == Decimal("206302.46")
    # Es un valor confirmado, no de ejemplo.
    assert (
        next(c for c in CONCEPTOS if c.codigo == "TASA_INTERES_MORA").tramos[0].a_confirmar is False
    )
