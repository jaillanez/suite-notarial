import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints

from app.modules.ddjj.schemas import ActoOut
from app.modules.ia.catalog import EstadoSugerencia, NivelAlerta, TipoSugerencia
from app.modules.ia.models import Sugerencia
from app.modules.ia.resultado import Resultado
from app.modules.padron.schemas import EscribanoDetalle


class CampoOut(BaseModel):
    """`valor` y `evidencia` vienen solo en la respuesta del análisis: no se guardan."""

    valor: str | None = None
    # Confianza 0 a 1 con 4 decimales, como texto (sin flotantes).
    confianza: str
    regla: str
    evidencia: str | None = None


class AlertaOut(BaseModel):
    codigo: str
    nivel: NivelAlerta
    # Solo en la respuesta del análisis (el mensaje puede citar datos del documento).
    mensaje: str | None = None
    evidencia: str | None = None


class EntradaOut(BaseModel):
    """Qué se analizó, sin el contenido (no se guarda)."""

    origen: str
    mime_type: str | None = None
    bytes: int | None = None
    caracteres: int | None = None
    paginas: int | None = None
    ocr: str | None = None
    # Índice del protocolo por foto: lote de la lectura, foto y renglón de esta sugerencia.
    lote: uuid.UUID | None = None
    foto: int | None = None
    renglon: int | None = None


class SugerenciaOut(BaseModel):
    id: uuid.UUID
    tipo: TipoSugerencia
    estado: EstadoSugerencia
    motor: str
    motor_version: str
    confianza: str
    tiempo_ms: int
    entrada: EntradaOut
    campos: dict[str, CampoOut]
    alertas: list[AlertaOut]
    ddjj_id: uuid.UUID | None
    campos_modificados: list[str] | None
    acto_id: uuid.UUID | None
    escribano_id: uuid.UUID | None
    resuelto_en: datetime | None
    created_at: datetime

    @classmethod
    def de(cls, s: Sugerencia, resultado: Resultado | None = None) -> "SugerenciaOut":
        """Con `resultado` (recién analizado), completa; sin él, lo que quedó registrado."""
        salida: dict[str, Any] = resultado.a_respuesta() if resultado else s.salida
        return cls(
            id=s.id,
            tipo=TipoSugerencia(s.tipo),
            estado=EstadoSugerencia(s.estado),
            motor=s.motor,
            motor_version=s.motor_version,
            confianza=str(s.confianza),
            tiempo_ms=s.tiempo_ms,
            entrada=EntradaOut.model_validate(s.entrada, strict=False),
            campos={k: CampoOut.model_validate(v) for k, v in salida["campos"].items()},
            alertas=[AlertaOut.model_validate(a) for a in salida["alertas"]],
            ddjj_id=s.ddjj_id,
            campos_modificados=s.campos_modificados,
            acto_id=s.acto_id,
            escribano_id=s.escribano_id,
            resuelto_en=s.resuelto_en,
            created_at=s.created_at,
        )


class ActoRatificadoOut(BaseModel):
    sugerencia: SugerenciaOut
    acto: ActoOut


class EscribanoRatificadoOut(BaseModel):
    sugerencia: SugerenciaOut
    escribano: EscribanoDetalle


class DescarteIn(BaseModel):
    motivo: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class EstadoIaOut(BaseModel):
    ocr_disponible: bool
    idiomas_ocr: str | None
    max_mb: int


class IndiceOut(BaseModel):
    """Lectura de las fotos del índice: una sugerencia de acto por renglón, en orden."""

    lote: uuid.UUID
    motor: str
    sugerencias: list[SugerenciaOut]
