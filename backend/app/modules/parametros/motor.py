"""Motor de cálculo de aportes (regla FIN): funciones puras sobre `Decimal`.

No accede a la base: recibe la fotografía (`VigenciaSnapshot`) de la vigencia con que se
calcula, de modo que el mismo cálculo se puede repetir exactamente sobre una boleta vieja.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.common.money import MONEY_QUANT, to_money
from app.modules.parametros.catalog import (
    ROUNDING_MODES,
    PeriodoTasa,
    ReglaRedondeo,
    TipoConcepto,
)

CIEN = Decimal(100)
# Días por período de la tasa para el interés diario lineal. La Caja confirmó (27/10/2026) que
# la tasa de mora es mensual con meses de 30 días. TODO(negocio): la base 365 de una tasa anual
# no está confirmada (hoy ninguna vigencia la usa).
DIAS_POR_PERIODO: dict[PeriodoTasa, Decimal] = {
    PeriodoTasa.MENSUAL: Decimal(30),
    PeriodoTasa.ANUAL: Decimal(365),
}


class MotorError(ValueError):
    """La vigencia no corresponde al cálculo pedido o los datos son inválidos."""


@dataclass(frozen=True)
class VigenciaSnapshot:
    vigencia_id: uuid.UUID
    concepto_codigo: str
    tipo: TipoConcepto
    fecha_desde: date
    fecha_hasta: date | None
    porcentaje: Decimal | None
    monto_fijo: Decimal | None
    monto_minimo: Decimal | None
    monto_maximo: Decimal | None
    tasa: Decimal | None
    periodo_tasa: PeriodoTasa | None
    dias_gracia: int | None
    regla_redondeo: ReglaRedondeo


def redondear(monto: Decimal, regla: ReglaRedondeo) -> Decimal:
    """Cuantiza a centavos con la regla de la vigencia (por defecto ROUND_HALF_UP)."""
    return monto.quantize(MONEY_QUANT, rounding=ROUNDING_MODES[regla])


def _require(v: VigenciaSnapshot, tipo: TipoConcepto) -> None:
    if v.tipo != tipo:
        raise MotorError(f"La vigencia de {v.concepto_codigo} es {v.tipo}, no {tipo}.")


def aporte_porcentual(base_imponible: Decimal, v: VigenciaSnapshot) -> Decimal:
    """`base * porcentaje / 100`, acotado por mínimo y tope, redondeado al final."""
    _require(v, TipoConcepto.PORCENTUAL_ACTO)
    if v.porcentaje is None:
        raise MotorError("La vigencia porcentual no tiene porcentaje.")
    base = to_money(base_imponible)
    if base < 0:
        raise MotorError("La base imponible no puede ser negativa.")
    bruto = base * v.porcentaje / CIEN
    if v.monto_minimo is not None and bruto < v.monto_minimo:
        bruto = v.monto_minimo
    if v.monto_maximo is not None and bruto > v.monto_maximo:
        bruto = v.monto_maximo
    return redondear(bruto, v.regla_redondeo)


def aporte_fijo(v: VigenciaSnapshot) -> Decimal:
    """Monto fijo de la vigencia: por acto (FIJO_ACTO) o por período mensual (FIJO_MENSUAL)."""
    if v.tipo not in (TipoConcepto.FIJO_ACTO, TipoConcepto.FIJO_MENSUAL):
        raise MotorError(f"La vigencia de {v.concepto_codigo} es {v.tipo}, no un monto fijo.")
    if v.monto_fijo is None:
        raise MotorError("La vigencia fija no tiene monto.")
    return redondear(v.monto_fijo, v.regla_redondeo)


def dias_de_mora(vencimiento: date, fecha_pago: date, v: VigenciaSnapshot) -> int:
    """Días de atraso computables.

    Pagado dentro de los días de gracia no hay mora; pasada la gracia se cuentan todos los
    días desde el vencimiento (la Caja confirmó que la mora corre desde el vencimiento; la
    vigente no tiene días de gracia).
    """
    _require(v, TipoConcepto.TASA_MORA)
    atraso = (fecha_pago - vencimiento).days
    if atraso <= (v.dias_gracia or 0):
        return 0
    return atraso


def interes_mora(monto: Decimal, dias: int, v: VigenciaSnapshot) -> Decimal:
    """Interés simple lineal: `monto * tasa / 100 / días del período * días` (Módulo 4 §3).

    Tasa mensual: base 30 días (confirmado por la Caja: interés simple, mes de 30 días); tasa
    anual: base 365 días.
    """
    _require(v, TipoConcepto.TASA_MORA)
    if v.tasa is None or v.periodo_tasa is None:
        raise MotorError("La vigencia de mora no tiene tasa o su unidad.")
    if dias < 0:
        raise MotorError("Los días de mora no pueden ser negativos.")
    if dias == 0 or v.tasa == 0:
        return Decimal("0.00")
    interes = to_money(monto) * v.tasa / CIEN / DIAS_POR_PERIODO[v.periodo_tasa] * Decimal(dias)
    return redondear(interes, v.regla_redondeo)


@dataclass(frozen=True)
class TramoMora:
    """Días de atraso en que rigió una misma tasa (`desde` y `hasta` inclusive)."""

    desde: date
    hasta: date
    dias: int
    vigencia: VigenciaSnapshot
    tasa: Decimal
    periodo_tasa: PeriodoTasa
    interes: Decimal


@dataclass(frozen=True)
class Mora:
    dias: int
    interes: Decimal
    tramos: tuple[TramoMora, ...]


def _vigencia_del_dia(vigencias: Sequence[VigenciaSnapshot], dia: date) -> VigenciaSnapshot:
    for v in vigencias:
        if v.fecha_desde <= dia and (v.fecha_hasta is None or dia <= v.fecha_hasta):
            return v
    raise MotorError(f"No hay tasa de mora vigente para el {dia:%d/%m/%Y}.")


def mora_por_tramos(
    monto: Decimal, vencimiento: date, fecha_pago: date, vigencias: Sequence[VigenciaSnapshot]
) -> Mora:
    """Interés simple sobre `monto` con la tasa vigente en cada día de atraso.

    Cada día posterior al vencimiento, hasta la fecha de pago inclusive, se calcula con la tasa
    vigente ese día (la Caja pidió que un cambio de tasa durante la mora se aplique por tramos).
    Los días de gracia son los de la tasa vigente al vencimiento.

    Redondeo: se suma el interés exacto de los tramos y se redondea el total una sola vez, con
    la regla de la tasa vigente al vencimiento; cada tramo se informa redondeado y el último
    absorbe la diferencia, para que el detalle sume exactamente el total impreso. Con una sola
    tasa da lo mismo que `interes_mora`. TODO(negocio): confirmar con la Caja si prefiere
    redondear cada tramo por separado (puede diferir en centavos).
    """
    for v in vigencias:
        _require(v, TipoConcepto.TASA_MORA)
        if v.tasa is None or v.periodo_tasa is None:
            raise MotorError("La vigencia de mora no tiene tasa o su unidad.")
    inicial = _vigencia_del_dia(vigencias, vencimiento)
    dias = dias_de_mora(vencimiento, fecha_pago, inicial)
    if dias == 0:
        return Mora(0, Decimal("0.00"), ())
    base = to_money(monto)
    partes: list[tuple[date, date, VigenciaSnapshot, Decimal, PeriodoTasa]] = []
    dia = vencimiento + timedelta(days=1)
    while dia <= fecha_pago:
        v = _vigencia_del_dia(vigencias, dia)
        assert v.tasa is not None and v.periodo_tasa is not None  # noqa: S101 - validado arriba
        hasta = fecha_pago if v.fecha_hasta is None else min(v.fecha_hasta, fecha_pago)
        partes.append((dia, hasta, v, v.tasa, v.periodo_tasa))
        dia = hasta + timedelta(days=1)
    exactos = [
        base * tasa / CIEN / DIAS_POR_PERIODO[periodo] * Decimal((h - d).days + 1)
        for d, h, _, tasa, periodo in partes
    ]
    total = redondear(sum(exactos, Decimal(0)), inicial.regla_redondeo)
    tramos: list[TramoMora] = []
    for i, ((d, h, v, tasa, periodo), exacto) in enumerate(zip(partes, exactos, strict=True)):
        ultimo = i == len(partes) - 1
        interes = (
            total - sum((t.interes for t in tramos), Decimal("0.00"))
            if ultimo
            else redondear(exacto, v.regla_redondeo)
        )
        tramos.append(TramoMora(d, h, (h - d).days + 1, v, tasa, periodo, interes))
    return Mora(dias, total, tuple(tramos))
