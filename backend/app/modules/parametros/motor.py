"""Motor de cálculo de aportes (regla FIN): funciones puras sobre `Decimal`.

No accede a la base: recibe la fotografía (`VigenciaSnapshot`) de la vigencia con que se
calcula, de modo que el mismo cálculo se puede repetir exactamente sobre una boleta vieja.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.money import MONEY_QUANT, to_money
from app.modules.parametros.catalog import (
    ROUNDING_MODES,
    PeriodoTasa,
    ReglaRedondeo,
    TipoConcepto,
)

CIEN = Decimal(100)
# Días por período de la tasa para el interés diario lineal.
# TODO(negocio): confirmar con la Caja la base (30/365 o días reales del mes/año).
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
    días desde el vencimiento. TODO(negocio): confirmar si la mora corre desde el vencimiento
    o desde el fin de la gracia.
    """
    _require(v, TipoConcepto.TASA_MORA)
    atraso = (fecha_pago - vencimiento).days
    if atraso <= (v.dias_gracia or 0):
        return 0
    return atraso


def interes_mora(monto: Decimal, dias: int, v: VigenciaSnapshot) -> Decimal:
    """Interés simple lineal: `monto * tasa / 100 / días del período * días` (Módulo 4 §3).

    Tasa mensual: base 30 días; tasa anual: base 365 días.
    TODO(negocio): confirmar con la Caja interés simple vs. compuesto y la base de días.
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
