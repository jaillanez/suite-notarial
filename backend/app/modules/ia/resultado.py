"""Resultado de un motor asistencial: campos propuestos con su respaldo y alertas."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.ia.catalog import CONFIANZA_QUANT, NivelAlerta


@dataclass
class Campo:
    valor: str | None
    confianza: Decimal
    regla: str
    evidencia: str | None = None

    def a_json(self) -> dict[str, Any]:
        return {
            "valor": self.valor,
            "confianza": str(self.confianza.quantize(CONFIANZA_QUANT)),
            "regla": self.regla,
            "evidencia": self.evidencia,
        }


@dataclass
class Alerta:
    codigo: str
    nivel: NivelAlerta
    mensaje: str
    evidencia: str | None = None

    def a_json(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "nivel": self.nivel.value,
            "mensaje": self.mensaje,
            "evidencia": self.evidencia,
        }


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

    def a_json(self) -> dict[str, Any]:
        return {
            "campos": {k: c.a_json() for k, c in self.campos.items()},
            "alertas": [a.a_json() for a in self.alertas],
        }
