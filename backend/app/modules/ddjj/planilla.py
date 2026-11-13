"""La DDJJ con el formato de la planilla de la Caja («Declaración Jurada de Aportes»).

La planilla que usa hoy la Caja tiene tres hojas: Protocolo General, Protocolo Auxiliar y
Resumen. Cada renglón es una escritura (o un acto de ella) con su base imponible, el aporte
variable o el fijo y el notario que la autorizó; el aporte va a la columna de su cargo (titular,
adscripto o a cargo). El Resumen da, por protocolo, el rango de escrituras y de folios y los
aportes de cada cargo.

Lo arma este módulo, con funciones puras, para que la pantalla y el PDF muestren lo mismo
(regla REP). No copia dos errores de la planilla: el total de la columna «Aporte» sumaba el 0,4 %
del encabezado, y el aporte fijo y los rangos del Resumen se escribían a mano.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.common.money import to_money
from app.modules.ddjj.catalog import CategoriaActo, MotivoExencion, TipoProtocolo
from app.modules.ddjj.liquidacion import AporteActo
from app.modules.padron.catalog import Cargo

CERO = Decimal("0.00")
FIJOS = (CategoriaActo.ACTA_O_PODER, CategoriaActo.OTRO_ACTO)
# Columnas de aporte de la planilla: «A Cargo» reúne a quien está interinamente a cargo.
COLUMNAS = (Cargo.TITULAR, Cargo.ADSCRIPTO, Cargo.SUPLENTE_INTERINO)


@dataclass(frozen=True)
class ActoPlanilla:
    """Lo que la planilla necesita de un acto declarado."""

    tipo_protocolo: TipoProtocolo
    numero_escritura: int
    orden_en_escritura: int
    folio: int | None
    naturaleza: str
    categoria: CategoriaActo
    base_imponible: Decimal
    escribano: str
    cargo: Cargo
    acto_id: uuid.UUID | None = None
    # Un acto exento declara por qué (va en la declaración jurada).
    motivo_exencion: MotivoExencion | None = None
    detalle_exencion: str | None = None


@dataclass(frozen=True)
class Renglon:
    acto_id: uuid.UUID | None
    numero_escritura: int
    orden_en_escritura: int
    folio: int | None
    naturaleza: str
    categoria: CategoriaActo
    motivo_exencion: MotivoExencion | None
    detalle_exencion: str | None
    base_imponible: Decimal | None
    # Variable o fijo, según la categoría (el otro queda vacío). None: sin aporte calculado.
    aporte_variable: Decimal | None
    aporte_fijo: Decimal | None
    escribano: str
    cargo: Cargo
    # Aporte del renglón en la columna de su cargo (después de la pluralidad de actos).
    aporte: Decimal | None
    incluido_en_otro: bool


@dataclass
class Totales:
    aporte_variable: Decimal = CERO
    aporte_fijo: Decimal = CERO
    por_cargo: dict[Cargo, Decimal] = field(default_factory=lambda: dict.fromkeys(COLUMNAS, CERO))

    @property
    def total(self) -> Decimal:
        return to_money(sum(self.por_cargo.values(), CERO))


@dataclass(frozen=True)
class Protocolo:
    tipo: TipoProtocolo
    renglones: tuple[Renglon, ...]
    totales: Totales
    escrituras_desde: int | None
    escrituras_hasta: int | None
    folios_desde: int | None
    folios_hasta: int | None


@dataclass(frozen=True)
class Planilla:
    protocolos: tuple[Protocolo, ...]
    totales: Totales
    # False si los aportes no se pudieron calcular (p. ej. falta un parámetro del período).
    con_aportes: bool


def _rango(valores: Sequence[int | None]) -> tuple[int | None, int | None]:
    presentes = [v for v in valores if v is not None]
    return (min(presentes), max(presentes)) if presentes else (None, None)


def armar(actos: Sequence[ActoPlanilla], aportes: Sequence[AporteActo] | None) -> Planilla:
    """Arma la planilla. `aportes` va en el orden de `actos` (None: sin calcular)."""
    if aportes is not None and len(aportes) != len(actos):
        raise ValueError("Cada acto necesita su aporte.")
    general = Totales()
    protocolos = []
    for tipo in TipoProtocolo:
        indices = sorted(
            (i for i, a in enumerate(actos) if a.tipo_protocolo is tipo),
            key=lambda i: (actos[i].numero_escritura, actos[i].orden_en_escritura),
        )
        totales = Totales()
        renglones = []
        for i in indices:
            acto = actos[i]
            calculado = aportes[i] if aportes is not None else None
            individual = calculado.aporte_individual if calculado else None
            variable = acto.categoria is CategoriaActo.ESCRITURA_CON_VALOR
            fijo = acto.categoria in FIJOS
            renglon = Renglon(
                acto_id=acto.acto_id,
                numero_escritura=acto.numero_escritura,
                orden_en_escritura=acto.orden_en_escritura,
                folio=acto.folio,
                naturaleza=acto.naturaleza,
                categoria=acto.categoria,
                motivo_exencion=acto.motivo_exencion,
                detalle_exencion=acto.detalle_exencion,
                base_imponible=acto.base_imponible if variable else None,
                aporte_variable=individual if variable else None,
                aporte_fijo=individual if fijo else None,
                escribano=acto.escribano,
                cargo=acto.cargo,
                aporte=calculado.aporte if calculado else None,
                incluido_en_otro=calculado.incluido_en_otro if calculado else False,
            )
            renglones.append(renglon)
            if calculado is None:
                continue
            for destino in (totales, general):
                # Las columnas «Aporte» y «Aporte fijo» suman lo que aporta cada acto solo; las
                # de cada cargo, lo que se paga (después de la pluralidad de actos).
                if variable:
                    destino.aporte_variable += calculado.aporte_individual
                if fijo:
                    destino.aporte_fijo += calculado.aporte_individual
                destino.por_cargo[acto.cargo] += calculado.aporte
        desde, hasta = _rango([actos[i].numero_escritura for i in indices])
        folio_desde, folio_hasta = _rango([actos[i].folio for i in indices])
        protocolos.append(
            Protocolo(tipo, tuple(renglones), totales, desde, hasta, folio_desde, folio_hasta)
        )
    return Planilla(tuple(protocolos), general, aportes is not None)
