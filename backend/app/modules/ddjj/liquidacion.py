"""Liquidación de una DDJJ (regla FIN): funciones puras sobre `Decimal`, sin base de datos.

Reproduce la boleta del sistema en uso (N° 1069, período 09/2026):

    total protocolos      = suma del aporte de cada acto
    excedente             = max(0, total protocolos - aporte mínimo mensual)
    total en término      = aporte mínimo + excedente + aporte médico
    interés               = mora sobre el total en término si se paga después del vencimiento
    total a pagar         = total en término + interés

TODO(negocio): confirmar con la Caja (a) que el aporte mínimo es un piso por registro y no por
escribano, y (b) que se cobra un aporte médico por cada titular o adscripto del registro (en el
reporte del sistema actual los actos de escribanos "a cargo" no llevan aporte médico).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.money import to_money
from app.modules.ddjj.catalog import CategoriaActo
from app.modules.parametros import motor
from app.modules.parametros.motor import VigenciaSnapshot

CERO = Decimal("0.00")


class LiquidacionError(ValueError):
    pass


@dataclass(frozen=True)
class ActoALiquidar:
    categoria: CategoriaActo
    base_imponible: Decimal


@dataclass(frozen=True)
class AporteActo:
    aporte: Decimal
    vigencia: VigenciaSnapshot | None


@dataclass(frozen=True)
class Liquidacion:
    aportes: tuple[AporteActo, ...]
    total_protocolos: Decimal
    aporte_minimo: Decimal
    excedente: Decimal
    aporte_medico: Decimal
    cantidad_aportes_medicos: int
    total_en_termino: Decimal
    dias_mora: int
    interes_mora: Decimal
    total_a_pagar: Decimal


def aporte_de_acto(acto: ActoALiquidar, vigencia: VigenciaSnapshot | None) -> AporteActo:
    if acto.categoria in (CategoriaActo.SIN_EFECTO, CategoriaActo.EXENTO):
        return AporteActo(CERO, None)
    if vigencia is None:
        raise LiquidacionError(f"Falta la vigencia para un acto {acto.categoria.value}.")
    if acto.categoria is CategoriaActo.ESCRITURA_CON_VALOR:
        if acto.base_imponible <= 0:
            raise LiquidacionError("Una escritura con valor necesita base imponible.")
        return AporteActo(motor.aporte_porcentual(acto.base_imponible, vigencia), vigencia)
    return AporteActo(motor.aporte_fijo(vigencia), vigencia)


def liquidar(
    actos: Sequence[tuple[ActoALiquidar, VigenciaSnapshot | None]],
    *,
    minimo: VigenciaSnapshot,
    medico: VigenciaSnapshot,
    cantidad_aportes_medicos: int,
    vencimiento: date,
    fecha_pago: date,
    mora: VigenciaSnapshot | None,
) -> Liquidacion:
    if cantidad_aportes_medicos < 0:
        raise LiquidacionError("La cantidad de aportes médicos no puede ser negativa.")
    aportes = tuple(aporte_de_acto(acto, vigencia) for acto, vigencia in actos)
    return totalizar(
        aportes,
        to_money(sum((a.aporte for a in aportes), CERO)),
        aporte_minimo=motor.aporte_fijo(minimo),
        aporte_medico=to_money(motor.aporte_fijo(medico) * cantidad_aportes_medicos),
        cantidad_aportes_medicos=cantidad_aportes_medicos,
        vencimiento=vencimiento,
        fecha_pago=fecha_pago,
        mora=mora,
    )


def totalizar(
    aportes: tuple[AporteActo, ...],
    total_protocolos: Decimal,
    *,
    aporte_minimo: Decimal,
    aporte_medico: Decimal,
    cantidad_aportes_medicos: int,
    vencimiento: date,
    fecha_pago: date,
    mora: VigenciaSnapshot | None,
) -> Liquidacion:
    """Mínimo, excedente e interés sobre importes ya calculados.

    Se usa también para reemitir una boleta con otra fecha de pago a partir de los importes
    congelados de la original: solo cambia la mora.
    """
    excedente = max(CERO, total_protocolos - aporte_minimo)
    total_en_termino = aporte_minimo + excedente + aporte_medico
    dias_mora = 0
    interes = CERO
    if fecha_pago > vencimiento:
        if mora is None:
            raise LiquidacionError("Falta la tasa de mora para pagar fuera de término.")
        dias_mora = motor.dias_de_mora(vencimiento, fecha_pago, mora)
        interes = motor.interes_mora(total_en_termino, dias_mora, mora)
    return Liquidacion(
        aportes=aportes,
        total_protocolos=total_protocolos,
        aporte_minimo=aporte_minimo,
        excedente=excedente,
        aporte_medico=aporte_medico,
        cantidad_aportes_medicos=cantidad_aportes_medicos,
        total_en_termino=total_en_termino,
        dias_mora=dias_mora,
        interes_mora=interes,
        total_a_pagar=total_en_termino + interes,
    )
