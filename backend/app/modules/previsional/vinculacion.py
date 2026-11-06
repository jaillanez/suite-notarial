"""Vínculo entre el nombre de la planilla y un escribano del padrón.

La planilla identifica al afiliado solo por el nombre («AGUILAR  Guillermo Ned»). Para no
asignar puntos a otra persona:
1. Coincidencia exacta del nombre normalizado (sin tildes, mayúsculas, signos ni espacios de
   más) con «apellido nombre» de un único escribano.
2. Si no hay exacta: coincidencia aproximada, solo si es única, cuando todas las palabras del
   nombre de la planilla están en el nombre del escribano (una inicial, «S.», vale por una
   palabra que empiece con esa letra). Es solo una SUGERENCIA: no atribuye puntos hasta que
   una persona la confirme.
3. Si hay más de un candidato o ninguno, no se vincula: queda en «Puntos sin vincular».
"""

import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.modules.previsional.catalog import Coincidencia

_NO_ALFANUMERICO = re.compile(r"[^0-9a-z]+")


def normalizar(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", nombre)
    limpio = "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()
    return " ".join(_NO_ALFANUMERICO.sub(" ", limpio).split())


@dataclass(frozen=True)
class Candidato:
    escribano_id: uuid.UUID
    nombre: str  # «apellido nombre» del padrón

    @property
    def normalizado(self) -> str:
        return normalizar(self.nombre)


@dataclass(frozen=True)
class Resultado:
    escribano_id: uuid.UUID | None
    coincidencia: Coincidencia | None
    # Más de un escribano posible: no se vincula.
    ambiguo: bool = False


def _contenido(palabras: list[str], destino: list[str]) -> bool:
    disponibles = list(destino)
    for palabra in palabras:
        if palabra in disponibles:
            disponibles.remove(palabra)
            continue
        if len(palabra) == 1:
            inicial = next((d for d in disponibles if d.startswith(palabra)), None)
            if inicial is not None:
                disponibles.remove(inicial)
                continue
        return False
    return True


class Vinculador:
    def __init__(self, candidatos: Iterable[Candidato]) -> None:
        self._candidatos = [(c, c.normalizado) for c in candidatos]
        self._exactos: dict[str, list[uuid.UUID]] = {}
        for c, norm in self._candidatos:
            self._exactos.setdefault(norm, []).append(c.escribano_id)

    def vincular(self, nombre_origen: str) -> Resultado:
        norm = normalizar(nombre_origen)
        if not norm:
            return Resultado(None, None)
        exactos = self._exactos.get(norm, [])
        if len(exactos) == 1:
            return Resultado(exactos[0], Coincidencia.EXACTA)
        if len(exactos) > 1:
            return Resultado(None, None, ambiguo=True)
        palabras = norm.split()
        # Una sola palabra (o solo iniciales) no alcanza para identificar a nadie.
        if sum(1 for p in palabras if len(p) > 1) < 2:
            return Resultado(None, None)
        posibles = [c.escribano_id for c, n in self._candidatos if _contenido(palabras, n.split())]
        if len(posibles) == 1:
            return Resultado(posibles[0], Coincidencia.APROXIMADA)
        return Resultado(None, None, ambiguo=len(posibles) > 1)
