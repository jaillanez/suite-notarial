"""Resultado de un motor asistencial: campos propuestos con su respaldo y alertas.

Dos representaciones (minimización de datos, Ley 25.326):

- `a_respuesta()`: completa (valores, fragmentos del documento, mensajes). Solo viaja en la
  respuesta del análisis, a la persona que pidió la lectura; no se guarda.
- `a_registro()`: lo que queda en `ia_sugerencias`, que no se borra. Por cada campo, la regla, la
  confianza y una huella HMAC del valor; por cada alerta, su código. Alcanza para auditar qué
  propuso el motor y qué corrigió la persona sin conservar datos personales ni texto de la minuta.
"""

import hashlib
import hmac
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.modules.ia.catalog import CONFIANZA_QUANT, NivelAlerta


@lru_cache
def _clave_huellas() -> bytes:
    # Subclave propia: la clave de cifrado de datos no se usa directamente para otro fin.
    return hmac.new(get_settings().data_encryption_key, b"ia-huellas-v1", hashlib.sha256).digest()


def huella(valor: str | None) -> str | None:
    """HMAC-SHA256 del valor: compara sin guardar el dato (un DNI no se recupera de su huella
    sin la clave del servidor)."""
    if valor is None:
        return None
    return hmac.new(_clave_huellas(), valor.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class Campo:
    valor: str | None
    confianza: Decimal
    regla: str
    evidencia: str | None = None

    def a_respuesta(self) -> dict[str, Any]:
        return {
            "valor": self.valor,
            "confianza": str(self.confianza.quantize(CONFIANZA_QUANT)),
            "regla": self.regla,
            "evidencia": self.evidencia,
        }

    def a_registro(self) -> dict[str, Any]:
        return {
            "confianza": str(self.confianza.quantize(CONFIANZA_QUANT)),
            "regla": self.regla,
            "huella": huella(self.valor),
        }


@dataclass
class Alerta:
    codigo: str
    nivel: NivelAlerta
    mensaje: str
    evidencia: str | None = None

    def a_respuesta(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "nivel": self.nivel.value,
            "mensaje": self.mensaje,
            "evidencia": self.evidencia,
        }

    def a_registro(self) -> dict[str, Any]:
        # El mensaje puede citar datos (un CUIT, un DNI): queda solo el código.
        return {"codigo": self.codigo, "nivel": self.nivel.value}


@dataclass
class Resultado:
    campos: dict[str, Campo]
    alertas: list[Alerta] = field(default_factory=list)

    def confianza(self) -> Decimal:
        """Promedio de los campos que se pudieron proponer (0 si ninguno)."""
        valores = [c.confianza for c in self.campos.values() if c.valor is not None]
        if not valores:
            return Decimal("0").quantize(CONFIANZA_QUANT)
        return (sum(valores, Decimal("0")) / len(valores)).quantize(CONFIANZA_QUANT)

    def a_respuesta(self) -> dict[str, Any]:
        return {
            "campos": {k: c.a_respuesta() for k, c in self.campos.items()},
            "alertas": [a.a_respuesta() for a in self.alertas],
        }

    def a_registro(self) -> dict[str, Any]:
        return {
            "campos": {k: c.a_registro() for k, c in self.campos.items()},
            "alertas": [a.a_registro() for a in self.alertas],
        }
