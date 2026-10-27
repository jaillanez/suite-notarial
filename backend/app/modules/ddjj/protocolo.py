"""Controles del libro de protocolo: numeración, folios y fechas de las escrituras.

En cada registro la numeración de escrituras es correlativa por protocolo (general o auxiliar)
y por año, y el folio y la fecha acompañan ese orden. Sobre los actos ya declarados en el año:

- número repetido: bloquea si está en otra DDJJ del año; en la misma DDJJ solo se admite como
  acto múltiple (varios actos de una misma escritura, cada uno en su renglón);
- folio repetido: advierte, salvo con la escritura inmediata anterior o siguiente (una escritura
  puede empezar en el folio donde terminó la otra);
- folio o fecha fuera de orden respecto de la numeración: advierte;
- números salteados entre la primera y la última escritura declaradas del año: se listan para
  declararlos «sin efecto» si no se usaron.

Cada consulta se hace con una `Vista` de quien consulta: el número repetido se controla contra
todo el año (es la regla que protege la integridad), pero si la otra escritura está en una DDJJ
fuera de su alcance el mensaje no dice cuál. Los avisos de folio y fecha y los números salteados
se calculan solo con las escrituras que puede ver: así ni el texto ni la presencia del aviso
revelan datos de DDJJ ajenas.

TODO(negocio): confirmar con la Caja que la numeración vuelve a empezar cada año calendario.
Las funciones de este módulo son puras; la consulta de los actos del año está en el servicio.
"""

import bisect
import itertools
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

# Tramos de números salteados que se informan (los demás se resumen en el total).
MAX_TRAMOS = 20


class NivelControl(StrEnum):
    BLOQUEANTE = "BLOQUEANTE"
    ADVERTENCIA = "ADVERTENCIA"


@dataclass(frozen=True)
class ActoDeclarado:
    id: uuid.UUID
    ddjj_id: uuid.UUID
    tipo_protocolo: str
    numero: int
    folio: int | None
    fecha: date
    periodo: str  # DDJJ donde está declarado ("aaaa-mm")


@dataclass(frozen=True)
class Candidato:
    tipo_protocolo: str
    numero: int | None
    folio: int | None
    fecha: date | None
    # DDJJ donde se carga o está el acto.
    ddjj_id: uuid.UUID | None = None
    # Otro acto de una escritura ya cargada en la misma DDJJ (aporte múltiple). Los actos ya
    # cargados se revisan como múltiples: sus hermanos de escritura no son un repetido.
    multiple: bool = False
    # Al revisar un acto ya cargado, se excluye a sí mismo.
    excluir: uuid.UUID | None = None


@dataclass(frozen=True)
class Control:
    codigo: str
    nivel: NivelControl
    mensaje: str


@dataclass(frozen=True)
class Hueco:
    tipo_protocolo: str
    # Tramos consecutivos (desde, hasta), en orden; se recorta a MAX_TRAMOS.
    tramos: tuple[tuple[int, int], ...]
    total: int  # cuántos números faltan en total


def _por_folio(
    a: ActoDeclarado | None, b: ActoDeclarado | None, mayor: bool
) -> ActoDeclarado | None:
    if a is None or a.folio is None:
        return b
    if b is None or b.folio is None:
        return a
    return b if (b.folio > a.folio if mayor else b.folio < a.folio) else a


def _por_fecha(a: ActoDeclarado, b: ActoDeclarado, mayor: bool) -> ActoDeclarado:
    return b if (b.fecha > a.fecha if mayor else b.fecha < a.fecha) else a


@dataclass
class _Protocolo:
    """Índice de un protocolo del año: cada control es O(log n), no un recorrido completo."""

    numeros: list[int] = field(default_factory=list)  # ordenados, sin repetir
    por_numero: dict[int, list[ActoDeclarado]] = field(default_factory=dict)
    por_folio: dict[int, list[ActoDeclarado]] = field(default_factory=dict)
    # Para la posición i de `numeros`: el acto de mayor folio / fecha entre numeros[: i + 1] y
    # el de menor folio / fecha entre numeros[i:].
    max_folio: list[ActoDeclarado | None] = field(default_factory=list)
    min_folio: list[ActoDeclarado | None] = field(default_factory=list)
    max_fecha: list[ActoDeclarado] = field(default_factory=list)
    min_fecha: list[ActoDeclarado] = field(default_factory=list)


class Indice:
    """Actos del año de un registro, indexados por protocolo (se arma una vez por consulta)."""

    def __init__(self, declarados: list[ActoDeclarado]) -> None:
        agrupados: dict[str, list[ActoDeclarado]] = defaultdict(list)
        for a in declarados:
            agrupados[a.tipo_protocolo].append(a)
        self.protocolos: dict[str, _Protocolo] = {}
        for tipo, actos in agrupados.items():
            p = _Protocolo()
            for a in actos:
                p.por_numero.setdefault(a.numero, []).append(a)
                if a.folio is not None:
                    p.por_folio.setdefault(a.folio, []).append(a)
            p.numeros = sorted(p.por_numero)
            folios: list[ActoDeclarado | None] = []
            fechas: list[ActoDeclarado] = []
            for n in p.numeros:
                grupo = p.por_numero[n]
                mejor: ActoDeclarado | None = None
                for a in grupo:
                    mejor = _por_folio(mejor, a, mayor=True)
                folios.append(mejor)
                fechas.append(max(grupo, key=lambda x: x.fecha))
            p.max_folio = list(itertools.accumulate(folios, lambda a, b: _por_folio(a, b, True)))
            p.min_folio = list(
                itertools.accumulate(reversed(folios), lambda a, b: _por_folio(a, b, False))
            )[::-1]
            p.max_fecha = list(itertools.accumulate(fechas, lambda a, b: _por_fecha(a, b, True)))
            p.min_fecha = list(
                itertools.accumulate(reversed(fechas), lambda a, b: _por_fecha(a, b, False))
            )[::-1]
            self.protocolos[tipo] = p


class Vista:
    """Lo que una persona puede consultar del protocolo del año de un registro."""

    def __init__(self, declarados: list[ActoDeclarado], visible: Callable[[str], bool]) -> None:
        self.completo = Indice(declarados)
        self.propio = Indice([a for a in declarados if visible(a.periodo)])
        self.visible = visible

    @classmethod
    def total(cls, declarados: list[ActoDeclarado]) -> "Vista":
        """Para quien ve todo el registro (personal de la Caja)."""
        return cls(declarados, lambda _periodo: True)


def _protocolo(tipo: str) -> str:
    return "general" if tipo == "GENERAL" else "auxiliar"


def _periodo(periodo: str) -> str:
    return f"{periodo[5:7]}/{periodo[:4]}"


def revisar(vista: Vista, c: Candidato) -> list[Control]:
    """Controles de un acto (nuevo o ya cargado) contra los declarados del mismo año."""
    if c.numero is None:
        return []
    controles: list[Control] = []
    protocolo = _protocolo(c.tipo_protocolo)
    completo = vista.completo.protocolos.get(c.tipo_protocolo)
    repetidos = (
        [a for a in completo.por_numero.get(c.numero, []) if a.id != c.excluir] if completo else []
    )
    en_otra = [a for a in repetidos if a.ddjj_id != c.ddjj_id]
    en_esta = [a for a in repetidos if a.ddjj_id == c.ddjj_id]
    if en_otra:
        donde = en_otra[0].periodo
        controles.append(
            Control(
                "NUMERO_REPETIDO",
                NivelControl.BLOQUEANTE,
                f"La escritura N° {c.numero} del protocolo {protocolo} ya está declarada "
                + (
                    f"en la DDJJ {_periodo(donde)}."
                    if vista.visible(donde)
                    else "en otra DDJJ del año."
                ),
            )
        )
    elif en_esta and not c.multiple:
        controles.append(
            Control(
                "NUMERO_REPETIDO",
                NivelControl.BLOQUEANTE,
                f"La escritura N° {c.numero} del protocolo {protocolo} ya está cargada en esta "
                "declaración. Si es otro acto de la misma escritura, marcalo como acto múltiple.",
            )
        )
    # Folio y fecha: solo contra lo que quien consulta puede ver.
    p = vista.propio.protocolos.get(c.tipo_protocolo)
    if p is None:
        return controles
    # Los números menores que el candidato son numeros[:menores]; los mayores, numeros[mayores:].
    menores = bisect.bisect_left(p.numeros, c.numero)
    mayores = bisect.bisect_right(p.numeros, c.numero)
    if c.folio is not None:
        mismo_folio = [
            a
            for a in p.por_folio.get(c.folio, [])
            if a.id != c.excluir and abs(a.numero - c.numero) > 1
        ]
        if mismo_folio:
            otro = mismo_folio[0]
            controles.append(
                Control(
                    "FOLIO_REPETIDO",
                    NivelControl.ADVERTENCIA,
                    f"El folio {c.folio} también figura en la escritura N° {otro.numero}: "
                    "verificalo en el libro.",
                )
            )
        antes = p.max_folio[menores - 1] if menores > 0 else None
        despues = p.min_folio[mayores] if mayores < len(p.numeros) else None
        fuera: ActoDeclarado | None = None
        if antes is not None and antes.folio is not None and antes.folio > c.folio:
            fuera = antes
        elif despues is not None and despues.folio is not None and despues.folio < c.folio:
            fuera = despues
        if fuera is not None:
            controles.append(
                Control(
                    "FOLIO_FUERA_DE_ORDEN",
                    NivelControl.ADVERTENCIA,
                    f"El folio {c.folio} no sigue el orden de la numeración: la escritura "
                    f"N° {fuera.numero} está en el folio {fuera.folio}.",
                )
            )
    if c.fecha is not None:
        antes_f = p.max_fecha[menores - 1] if menores > 0 else None
        despues_f = p.min_fecha[mayores] if mayores < len(p.numeros) else None
        fuera_f: ActoDeclarado | None = None
        if antes_f is not None and antes_f.fecha > c.fecha:
            fuera_f = antes_f
        elif despues_f is not None and despues_f.fecha < c.fecha:
            fuera_f = despues_f
        if fuera_f is not None:
            controles.append(
                Control(
                    "FECHA_FUERA_DE_ORDEN",
                    NivelControl.ADVERTENCIA,
                    "La fecha no sigue el orden de la numeración: la escritura "
                    f"N° {fuera_f.numero} es del {fuera_f.fecha:%d/%m/%Y}.",
                )
            )
    return controles


def huecos(vista: Vista) -> list[Hueco]:
    """Números sin declarar entre la primera y la última escritura del año que quien consulta
    puede ver, por protocolo, agrupados en tramos consecutivos ("43 a 100")."""
    resultado = []
    for tipo in ("GENERAL", "AUXILIAR"):
        p = vista.propio.protocolos.get(tipo)
        if p is None:
            continue
        tramos: list[tuple[int, int]] = []
        total = 0
        for anterior, siguiente in itertools.pairwise(p.numeros):
            if siguiente - anterior > 1:
                tramos.append((anterior + 1, siguiente - 1))
                total += siguiente - anterior - 1
        if tramos:
            resultado.append(Hueco(tipo, tuple(tramos[:MAX_TRAMOS]), total))
    return resultado
