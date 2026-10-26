"""Homologación de los códigos del sistema anterior al catálogo de la Suite.

TODO(negocio): la tabla definitiva la aprueba la Caja tras auditar el origen (D-03). Hasta
entonces se usa `homologacion_ejemplo.json`, marcado como ejemplo: sirve para simulacros, pero
una carga definitiva con una homologación de ejemplo se rechaza. Un código que no figura en la
tabla nunca se adivina: la fila queda observada.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.modules.migracion.catalog import EstadoBoletaHistorica
from app.modules.padron.catalog import Cargo, EstadoMatricula, EstadoRegistro

EJEMPLO = Path(__file__).with_name("homologacion_ejemplo.json")
CATALOGOS: dict[str, frozenset[str]] = {
    "estado_escribano": frozenset(e.value for e in EstadoMatricula),
    "estado_registro": frozenset(e.value for e in EstadoRegistro),
    "cargo": frozenset(c.value for c in Cargo),
    "estado_boleta": frozenset(e.value for e in EstadoBoletaHistorica),
}


class HomologacionInvalidaError(ValueError):
    pass


@dataclass(frozen=True)
class Homologacion:
    tablas: dict[str, dict[str, str]]
    es_ejemplo: bool
    origen: str

    def traducir(self, tabla: str, codigo: str) -> str | None:
        return self.tablas[tabla].get(codigo.strip().upper())


def cargar(ruta: Path | None = None) -> Homologacion:
    archivo = ruta or EJEMPLO
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HomologacionInvalidaError(f"No se pudo leer {archivo.name}: {exc}") from exc
    tablas: dict[str, dict[str, str]] = {}
    for tabla, validos in CATALOGOS.items():
        entradas = datos.get(tabla)
        if not isinstance(entradas, dict) or not entradas:
            raise HomologacionInvalidaError(f"{archivo.name}: falta la tabla «{tabla}».")
        traducidas: dict[str, str] = {}
        for origen, destino in entradas.items():
            if destino not in validos:
                raise HomologacionInvalidaError(
                    f"{archivo.name}: «{origen}» → «{destino}» no es un valor de {tabla}."
                )
            traducidas[str(origen).strip().upper()] = destino
        tablas[tabla] = traducidas
    return Homologacion(tablas, bool(datos.get("es_ejemplo", False)), archivo.name)
