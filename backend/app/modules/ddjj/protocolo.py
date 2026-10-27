"""Controles del libro de protocolo: numeración, folios y fechas de las escrituras.

En cada registro la numeración de escrituras es correlativa por protocolo (general o auxiliar)
y por año, y el folio y la fecha acompañan ese orden. Sobre los actos ya declarados en el año:

- número repetido (en cualquier DDJJ del año): bloquea, una escritura se declara una sola vez;
- folio repetido: advierte, salvo con la escritura inmediata anterior o siguiente (una escritura
  puede empezar en el folio donde terminó la otra);
- folio o fecha fuera de orden respecto de la numeración: advierte;
- números salteados entre la primera y la última escritura declaradas del año: se listan para
  declararlos «sin efecto» si no se usaron.

TODO(negocio): confirmar con la Caja que la numeración vuelve a empezar cada año calendario.
Las funciones de este módulo son puras; la consulta de los actos del año está en el servicio.
"""

import itertools
import uuid
from dataclasses import dataclass
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


def _protocolo(tipo: str) -> str:
    return "general" if tipo == "GENERAL" else "auxiliar"


def _periodo(periodo: str) -> str:
    return f"{periodo[5:7]}/{periodo[:4]}"


def revisar(declarados: list[ActoDeclarado], c: Candidato) -> list[Control]:
    """Controles de un acto (nuevo o ya cargado) contra los declarados del mismo año."""
    mismos = [a for a in declarados if a.tipo_protocolo == c.tipo_protocolo and a.id != c.excluir]
    controles: list[Control] = []
    if c.numero is None:
        return controles
    protocolo = _protocolo(c.tipo_protocolo)
    repetido = next((a for a in mismos if a.numero == c.numero), None)
    if repetido is not None:
        controles.append(
            Control(
                "NUMERO_REPETIDO",
                NivelControl.BLOQUEANTE,
                f"La escritura N° {c.numero} del protocolo {protocolo} ya está declarada en la "
                f"DDJJ {_periodo(repetido.periodo)}.",
            )
        )
    otros = [a for a in mismos if a.numero != c.numero]
    if c.folio is not None:
        mismo_folio = [a for a in otros if a.folio == c.folio and abs(a.numero - c.numero) > 1]
        if mismo_folio:
            controles.append(
                Control(
                    "FOLIO_REPETIDO",
                    NivelControl.ADVERTENCIA,
                    f"El folio {c.folio} también figura en la escritura N° "
                    f"{mismo_folio[0].numero}: verificalo en el libro.",
                )
            )
        desordenado = next(
            (
                a
                for a in otros
                if a.folio is not None
                and (
                    (a.numero < c.numero and a.folio > c.folio)
                    or (a.numero > c.numero and a.folio < c.folio)
                )
            ),
            None,
        )
        if desordenado is not None:
            controles.append(
                Control(
                    "FOLIO_FUERA_DE_ORDEN",
                    NivelControl.ADVERTENCIA,
                    f"El folio {c.folio} no sigue el orden de la numeración: la escritura N° "
                    f"{desordenado.numero} está en el folio {desordenado.folio}.",
                )
            )
    if c.fecha is not None:
        desordenada = next(
            (
                a
                for a in otros
                if (a.numero < c.numero and a.fecha > c.fecha)
                or (a.numero > c.numero and a.fecha < c.fecha)
            ),
            None,
        )
        if desordenada is not None:
            controles.append(
                Control(
                    "FECHA_FUERA_DE_ORDEN",
                    NivelControl.ADVERTENCIA,
                    f"La fecha no sigue el orden de la numeración: la escritura N° "
                    f"{desordenada.numero} es del {desordenada.fecha:%d/%m/%Y}.",
                )
            )
    return controles


def huecos(declarados: list[ActoDeclarado]) -> list[Hueco]:
    """Números sin declarar entre la primera y la última escritura del año, por protocolo,
    agrupados en tramos consecutivos ("43 a 100" en vez de 58 números sueltos)."""
    resultado = []
    for tipo in ("GENERAL", "AUXILIAR"):
        numeros = sorted({a.numero for a in declarados if a.tipo_protocolo == tipo})
        tramos: list[tuple[int, int]] = []
        total = 0
        for anterior, siguiente in itertools.pairwise(numeros):
            if siguiente - anterior > 1:
                tramos.append((anterior + 1, siguiente - 1))
                total += siguiente - anterior - 1
        if tramos:
            resultado.append(Hueco(tipo, tuple(tramos[:MAX_TRAMOS]), total))
    return resultado
