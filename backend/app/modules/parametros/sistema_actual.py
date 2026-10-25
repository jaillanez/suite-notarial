"""Parámetros 2026 tal como figuran en el sistema en uso de la Caja (relevados el 25/10/2026).

Fuente: pantalla "Parámetros - Aportes previsionales mínimos y máximos, y aportes médico
asistenciales" y su "Listado de Aportes AÑO 2026" (períodos 01/2026 a 10/2026). Verificado contra
el "Reporte Mensual de Boletas" de agosto-septiembre: las 351 escrituras con base imponible
cumplen `aporte = base * 0,40 %` acotado por el mínimo y el tope del período.

Cada valor rige desde el primer día del período (mes devengado). No se citan resoluciones porque
la pantalla no las muestra: TODO(negocio) completar el respaldo de cada vigencia.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.modules.parametros.catalog import PeriodoTasa, TipoConcepto

FUENTE = "Sistema actual de la Caja (pantalla Parámetros 2026), sin resolución citada"


@dataclass(frozen=True)
class Tramo:
    desde: date
    hasta: date | None
    valores: dict[str, object]
    # Valor cuyo significado no está confirmado: se muestra como "ejemplo" (no oficial).
    a_confirmar: bool = False


@dataclass(frozen=True)
class ConceptoRelevado:
    codigo: str
    nombre: str
    tipo: TipoConcepto
    descripcion: str
    tramos: tuple[Tramo, ...] = field(default_factory=tuple)


D = Decimal


def _mensuales(montos: list[tuple[int, str]]) -> tuple[Tramo, ...]:
    """Un tramo por mes de 2026; el último queda abierto."""
    tramos = []
    for i, (mes, monto) in enumerate(montos):
        es_ultimo = i == len(montos) - 1
        siguiente = date(2026, montos[i + 1][0], 1) if not es_ultimo else None
        hasta = None if siguiente is None else date.fromordinal(siguiente.toordinal() - 1)
        tramos.append(Tramo(date(2026, mes, 1), hasta, {"monto_fijo": D(monto)}))
    return tuple(tramos)


CONCEPTOS: tuple[ConceptoRelevado, ...] = (
    ConceptoRelevado(
        "APORTE_ESCRITURA",
        "Aporte variable por escrituras",
        TipoConcepto.PORCENTUAL_ACTO,
        "Porcentaje sobre el valor de la escritura, con mínimo y máximo por escritura.",
        (
            Tramo(
                date(2026, 1, 1),
                date(2026, 5, 31),
                {
                    "porcentaje": D("0.4000"),
                    "monto_minimo": D("52081.00"),
                    "monto_maximo": D("2618550.00"),
                },
            ),
            Tramo(
                date(2026, 6, 1),
                None,
                {
                    "porcentaje": D("0.4000"),
                    "monto_minimo": D("57289.00"),
                    "monto_maximo": D("3482672.00"),
                },
            ),
        ),
    ),
    ConceptoRelevado(
        "APORTE_FIJO_ACTAS_PODERES",
        "Aporte fijo por actas y poderes",
        TipoConcepto.FIJO_ACTO,
        "Monto fijo por cada acta o poder.",
        (
            Tramo(date(2026, 1, 1), date(2026, 5, 31), {"monto_fijo": D("9020.00")}),
            Tramo(date(2026, 6, 1), None, {"monto_fijo": D("9922.00")}),
        ),
    ),
    ConceptoRelevado(
        "APORTE_FIJO_OTROS_ACTOS",
        "Aporte fijo por otros actos",
        TipoConcepto.FIJO_ACTO,
        "Monto fijo por cada acto sin base imponible que no es acta ni poder.",
        (
            Tramo(date(2026, 1, 1), date(2026, 5, 31), {"monto_fijo": D("34042.00")}),
            Tramo(date(2026, 6, 1), None, {"monto_fijo": D("37446.00")}),
        ),
    ),
    ConceptoRelevado(
        "APORTE_MINIMO_MENSUAL",
        "Aporte previsional mínimo mensual",
        TipoConcepto.FIJO_MENSUAL,
        "Piso mensual de los aportes por protocolo: si el total del mes es menor, se paga este "
        "mínimo (lo que lo supera es el excedente).",
        (
            Tramo(date(2026, 1, 1), date(2026, 5, 31), {"monto_fijo": D("78120.00")}),
            Tramo(date(2026, 6, 1), None, {"monto_fijo": D("85932.00")}),
        ),
    ),
    ConceptoRelevado(
        "APORTE_MEDICO_ASISTENCIAL",
        "Aporte médico asistencial mensual",
        TipoConcepto.FIJO_MENSUAL,
        "Monto mensual que se suma a la boleta de cada período.",
        _mensuales(
            [
                (1, "76000.00"),
                (2, "78000.00"),
                (3, "81000.00"),
                (4, "84000.00"),
                (5, "87000.00"),
                (6, "90000.00"),
                (7, "93000.00"),
                (8, "95000.00"),
                (9, "97000.00"),
                (10, "100000.00"),
            ]
        ),
    ),
    ConceptoRelevado(
        "TASA_INTERES_MORA",
        "Tasa de interés por pago fuera de término",
        TipoConcepto.TASA_MORA,
        "La pantalla muestra «34» sin unidad. Se interpreta como 34 % anual porque un 34 % "
        "mensual no es verosímil. TODO(negocio): confirmar unidad, base de días y gracia.",
        (
            Tramo(
                date(2026, 1, 1),
                None,
                {"tasa": D("34.0000"), "periodo_tasa": PeriodoTasa.ANUAL.value, "dias_gracia": 0},
                a_confirmar=True,
            ),
        ),
    ),
)

# Fecha de vencimiento de la obligación de pago por período (mes devengado). La usará el
# cálculo de boletas (Fase 4); no es una vigencia sino un calendario por período.
VENCIMIENTOS_2026: dict[int, date] = {
    1: date(2026, 3, 2),
    2: date(2026, 3, 30),
    3: date(2026, 4, 28),
    4: date(2026, 5, 28),
    5: date(2026, 6, 29),
    6: date(2026, 7, 28),
    7: date(2026, 8, 28),
    8: date(2026, 9, 28),
    9: date(2026, 10, 28),
    10: date(2026, 11, 30),
}
