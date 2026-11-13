"""Liquidación de una DDJJ (regla FIN): funciones puras sobre `Decimal`, sin base de datos.

Reproduce la boleta del sistema en uso (N° 1069, período 09/2026):

    total protocolos      = suma del aporte de cada acto
    excedente             = max(0, total protocolos - aporte mínimo mensual)
    total en término      = aporte mínimo + excedente + aporte médico
    interés               = mora sobre el total en término si se paga después del vencimiento
    total a pagar         = total en término + interés

Cada escribano del registro tiene su propia boleta y la paga en su fecha (contrato, Anexo I):
titular y adscripto pagan cada uno su mínimo, su aporte médico y el excedente sobre sus propios
actos, como en el sistema de la Caja (planilla de pagos 2019-2026: el 98 % de los adscriptos pagó
el mismo mínimo y médico que su titular). Quien está a cargo no paga el médico por ese registro
(confirmado por la Caja el 27/10/2026); qué paga lo fija la Caja en cada designación.

Varios actos en una misma escritura con las mismas partes aportan según el criterio de
pluralidad vigente (parámetro CRITERIO_PLURALIDAD_ACTOS; vademécum 2026: solo el de mayor
valor). Con partes distintas, o sin criterio vigente, aporta cada acto.

`liquidar` calcula una boleta; `liquidar_por_escribano`, las del equipo del registro.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.money import to_money
from app.modules.ddjj.catalog import CategoriaActo, ModalidadBoleta
from app.modules.parametros import motor
from app.modules.parametros.catalog import CriterioPluralidad
from app.modules.parametros.motor import VigenciaSnapshot

CERO = Decimal("0.00")


class LiquidacionError(ValueError):
    pass


@dataclass(frozen=True)
class ActoALiquidar:
    categoria: CategoriaActo
    base_imponible: Decimal
    # Escritura a la que pertenece (protocolo, número): sus actos se agrupan para la pluralidad.
    escritura: tuple[str, int] | None = None
    mismas_partes: bool = True


@dataclass(frozen=True)
class AporteActo:
    aporte: Decimal
    vigencia: VigenciaSnapshot | None
    # Lo que aportaría el acto solo (None: igual a `aporte`). Difiere cuando el criterio de
    # pluralidad lo deja incluido en otro acto de la misma escritura.
    individual: Decimal | None = None
    pluralidad: VigenciaSnapshot | None = None

    @property
    def aporte_individual(self) -> Decimal:
        return self.aporte if self.individual is None else self.individual

    @property
    def incluido_en_otro(self) -> bool:
        return self.aporte < self.aporte_individual


FIJOS = (CategoriaActo.ACTA_O_PODER, CategoriaActo.OTRO_ACTO)


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
    # Interés por tasa vigente en cada tramo de días de atraso.
    tramos_mora: tuple[motor.TramoMora, ...] = ()


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


def _que_aportan(
    grupo: list[tuple[int, ActoALiquidar, AporteActo]], criterio: CriterioPluralidad
) -> set[int]:
    """Índices de los actos de una escritura que conservan su aporte. Ante empate gana el
    primero declarado, para que el resultado no dependa de nada más que del orden."""

    def mayor(items: list[tuple[int, ActoALiquidar, AporteActo]]) -> set[int]:
        if not items:
            return set()
        tope = max(a.aporte for _, _, a in items)
        return {next(i for i, _, a in items if a.aporte == tope)}

    if criterio is CriterioPluralidad.SUMAN_TODOS:
        return {i for i, _, _ in grupo}
    if criterio is CriterioPluralidad.SOLO_EL_MAYOR:
        return mayor(grupo)
    variables = {i for i, acto, _ in grupo if acto.categoria not in FIJOS}
    return variables | mayor([g for g in grupo if g[1].categoria in FIJOS])


def aplicar_pluralidad(
    actos: Sequence[ActoALiquidar],
    aportes: Sequence[AporteActo],
    pluralidad: VigenciaSnapshot | None,
) -> tuple[AporteActo, ...]:
    """Aplica el criterio vigente a cada escritura con varios actos y las mismas partes.

    Los actos que quedan incluidos en otro aportan 0 pero guardan su aporte individual, para
    mostrar por qué. Sin vigencia de criterio, aporta cada acto (como hasta junio de 2026).
    """
    if len(actos) != len(aportes):
        raise LiquidacionError("Cada acto necesita su aporte.")
    if pluralidad is None:
        return tuple(aportes)
    if pluralidad.criterio is None:
        raise LiquidacionError("La vigencia del criterio de pluralidad no tiene criterio.")
    grupos: dict[tuple[str, int], list[tuple[int, ActoALiquidar, AporteActo]]] = {}
    for i, (acto, aporte) in enumerate(zip(actos, aportes, strict=True)):
        if acto.escritura is not None:
            grupos.setdefault(acto.escritura, []).append((i, acto, aporte))
    resultado = list(aportes)
    for grupo in grupos.values():
        if len(grupo) < 2 or not all(acto.mismas_partes for _, acto, _ in grupo):
            continue
        conservan = _que_aportan(grupo, pluralidad.criterio)
        for i, _, aporte in grupo:
            resultado[i] = AporteActo(
                aporte.aporte if i in conservan else CERO,
                aporte.vigencia,
                individual=aporte.aporte,
                pluralidad=pluralidad,
            )
    return tuple(resultado)


def liquidar(
    actos: Sequence[tuple[ActoALiquidar, VigenciaSnapshot | None]],
    *,
    minimo: VigenciaSnapshot,
    medico: VigenciaSnapshot,
    cantidad_aportes_medicos: int,
    vencimiento: date,
    fecha_pago: date,
    mora: Sequence[VigenciaSnapshot],
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
    mora: Sequence[VigenciaSnapshot],
) -> Liquidacion:
    """Mínimo, excedente e interés sobre importes ya calculados.

    `mora` son las tasas de mora vigentes entre el vencimiento y la fecha de pago (vacío si se
    paga en término): cada tramo de días se calcula con la suya.

    Se usa también para reemitir una boleta con otra fecha de pago a partir de los importes
    congelados de la original: solo cambia la mora.
    """
    excedente = max(CERO, total_protocolos - aporte_minimo)
    total_en_termino = aporte_minimo + excedente + aporte_medico
    calculo = motor.Mora(0, CERO, ())
    if fecha_pago > vencimiento:
        if not mora:
            raise LiquidacionError("Falta la tasa de mora para pagar fuera de término.")
        try:
            calculo = motor.mora_por_tramos(total_en_termino, vencimiento, fecha_pago, mora)
        except motor.MotorError as exc:
            raise LiquidacionError(str(exc)) from exc
    return Liquidacion(
        aportes=aportes,
        total_protocolos=total_protocolos,
        aporte_minimo=aporte_minimo,
        excedente=excedente,
        aporte_medico=aporte_medico,
        cantidad_aportes_medicos=cantidad_aportes_medicos,
        total_en_termino=total_en_termino,
        dias_mora=calculo.dias,
        interes_mora=calculo.interes,
        total_a_pagar=total_en_termino + calculo.interes,
        tramos_mora=calculo.tramos,
    )


@dataclass(frozen=True)
class Obligado:
    """Escribano del equipo del registro en el período y qué le cobra su boleta.

    `modalidad` None: no tiene boleta propia, sus actos van a la del titular (a cargo con
    AporteACargo.EN_BOLETA_DEL_TITULAR).
    """

    escribano_id: uuid.UUID
    cargo: str
    modalidad: ModalidadBoleta | None


@dataclass(frozen=True)
class LiquidacionEscribano:
    obligado: Obligado
    modalidad: ModalidadBoleta
    liquidacion: Liquidacion


TITULAR = "TITULAR"
SIN_TITULAR_UNICO = (
    "Los actos del escribano a cargo se cobran en la boleta del titular, pero el registro no "
    "tiene un único titular en el período: la Caja tiene que fijar otra forma de aporte en la "
    "designación."
)
ACTO_SIN_CARGO = "Hay actos de un escribano que no integra el registro en el período."


def liquidar_por_escribano(
    actos: Sequence[tuple[uuid.UUID, ActoALiquidar, VigenciaSnapshot | None]],
    obligados: Sequence[Obligado],
    *,
    minimo: VigenciaSnapshot,
    medico: VigenciaSnapshot,
    vencimiento: date,
    fecha_pago: date,
    mora: Sequence[VigenciaSnapshot],
    pluralidad: VigenciaSnapshot | None = None,
) -> tuple[tuple[AporteActo, ...], tuple[LiquidacionEscribano, ...]]:
    """Aporte de cada acto (en el orden recibido) y una liquidación por escribano con boleta.

    Cada acto suma al escribano que lo autorizó, o al titular si ese escribano está a cargo con
    sus actos en la boleta del titular. Quien está a cargo solo por sus actos y no tiene nada que
    aportar no recibe boleta.
    """
    por_id = {o.escribano_id: o for o in obligados}
    if len(por_id) != len(obligados):
        raise LiquidacionError("Un escribano figura dos veces en el equipo del registro.")
    titulares = [o for o in obligados if o.cargo == TITULAR]

    def destino(escribano_id: uuid.UUID) -> uuid.UUID:
        obligado = por_id.get(escribano_id)
        if obligado is None:
            raise LiquidacionError(ACTO_SIN_CARGO)
        if obligado.modalidad is not None:
            return escribano_id
        if len(titulares) != 1:
            raise LiquidacionError(SIN_TITULAR_UNICO)
        return titulares[0].escribano_id

    aportes = aplicar_pluralidad(
        [acto for _, acto, _ in actos],
        [aporte_de_acto(acto, vigencia) for _, acto, vigencia in actos],
        pluralidad,
    )
    propios: dict[uuid.UUID, list[AporteActo]] = {}
    for (escribano_id, _, _), aporte in zip(actos, aportes, strict=True):
        propios.setdefault(destino(escribano_id), []).append(aporte)

    boletas: list[LiquidacionEscribano] = []
    for o in obligados:
        if o.modalidad is None:
            continue
        suyos = tuple(propios.get(o.escribano_id, ()))
        protocolos = to_money(sum((a.aporte for a in suyos), CERO))
        # Sin nada que cobrar (sin actos, o solo exentos o sin efecto) no hay boleta.
        if o.modalidad is ModalidadBoleta.SOLO_ACTOS and protocolos == CERO:
            continue
        con_medico = o.modalidad is ModalidadBoleta.COMPLETA
        liquidacion = totalizar(
            suyos,
            protocolos,
            aporte_minimo=CERO
            if o.modalidad is ModalidadBoleta.SOLO_ACTOS
            else motor.aporte_fijo(minimo),
            aporte_medico=motor.aporte_fijo(medico) if con_medico else CERO,
            cantidad_aportes_medicos=1 if con_medico else 0,
            vencimiento=vencimiento,
            fecha_pago=fecha_pago,
            mora=mora,
        )
        boletas.append(LiquidacionEscribano(o, o.modalidad, liquidacion))
    return aportes, tuple(boletas)
