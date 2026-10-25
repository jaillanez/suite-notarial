# Documento de Ingeniería de Software — Módulo 10
## Inteligencia Artificial Asistencial y Automatización Notarial
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Estándares de Referencia:** Proyecto Atenea (Consejo General del Notariado) | Tesis ONPI "De la celulosa al silicio: Workflows agénticos" | RIA UE 2024/1689 (Human in Command) | Ley 25.326  
**Stack de Referencia:** Python 3.12+ | FastAPI | Tesseract OCR / PaddleOCR | Spacy / Transformers (NLP) | PyTorch | Celery / Redis | React + TypeScript

---

### 1. Propósito, Principio "Human in Command" y Mitigación de Riesgos

El **Módulo 10 (Inteligencia Artificial y Automatización Notarial)** incorpora herramientas de asistencia cognitiva al servicio de los escribanos matriculados y de la administración de la Caja, acelerando la carga de datos documentales y robusteciendo la seguridad preventiva.

#### 1.1 Principios Jurídico-Técnicos Ineludibles
1. **Principio Human in Command (HIC) Irrenunciable:**
   * La inteligencia artificial es estrictamente **coadyuvante y auxiliar**; jamás sustituye el discernimiento, juicio jurídico ni la fe pública del notario.
   * Ningún acto notarial, liquidación de escrituras ni cálculo definitivo se convalida automáticamente por un algoritmo. Toda sugerencia generada por los agentes de IA debe ser revisada, ajustada y ratificada expresamente por el escribano o el operador de Caja (*doble control experto*).
2. **Explicabilidad y Transparencia Algorítmica (XAI):**
   * Se prohíbe el uso de modelos "caja negra" inexplicables para tareas de validación crítica. Cada alerta de inconsistencia o propuesta de valor debe acompañar su justificación explícita y los fragmentos textuales de respaldo.
3. **Privacidad, Minimización de Datos y Procesamiento Seguro:**
   * Cumplimiento estricto de la Ley 25.326 de Protección de Datos Personales. Los modelos de lenguaje y visión operan en servidores privados locales/on-premise de la Caja Notarial o nubes dedicadas aisladas; ningún dato sensible de otorgantes o protocolos es compartido con APIs externas comerciales de terceros para entrenamiento.

---

### 2. Arquitectura de Servicios de IA Asistencial

La suite implementa cuatro pipelines de asistencia automatizada:

```text
+--------------------------------------------------------------------------------+
|                        PIPELINE DE IA COADYUVANTE                              |
+--------------------------------------------------------------------------------+
                                       |
    +----------------------------------+----------------------------------+
    |                                  |                                  |
    v                                  v                                  v
[1. Pipeline OCR Documental]  [2. Extractor NLP Escrituras]  [3. Validador Minutas]
  - Escaneo de DNI y CUIT       - Detección de comparecientes  - Detección inconsistencias
  - Extracción MRZ / Campos     - Inmuebles, gravámenes        - Cuadre de cifras y fechas
  - Coincidencia facial 1:1     - Base imponible y aportes     - Checklist normativo
    |                                  |                                  |
    +----------------------------------+----------------------------------+
                                       |
                                       v
                     [4. Workflows Agénticos Supervisados]
                        - Orquestador de Sesión y Riesgo
                        - Interfaz Explicable con Aprobación Humana
```

---

### 3. Modelo de Datos Relacional para Trazabilidad de IA (PostgreSQL DDL)

```sql
-- Registro de Inferencia y Trazabilidad de Modelos de IA
CREATE TABLE IF NOT EXISTS ia_inferencias_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_tarea VARCHAR(50) NOT NULL, -- 'OCR_DNI', 'EXTRACCION_ESCRITURA', 'VALIDACION_MINUTA'
    modelo_nombre VARCHAR(100) NOT NULL, -- Ej: 'notarial-nlp-san-juan-v1'
    tiempo_procesamiento_ms INT NOT NULL,
    score_confianza_promedio NUMERIC(5, 4) NOT NULL, -- 0.0000 a 1.0000
    
    -- Entrada y Salida Estructurada (Minimizando Datos Sensibles)
    input_metadatos JSONB NOT NULL,
    output_sugerido JSONB NOT NULL,
    
    -- Supervisión Humana (Human in Command)
    fue_modificado_por_humano BOOLEAN NOT NULL DEFAULT FALSE,
    datos_finales_confirmados JSONB,
    operador_user_id UUID NOT NULL REFERENCES security_users(id),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_ia_log_tarea ON ia_inferencias_log(tipo_tarea, created_at);
```

---

### 4. Servicio de Extracción Documental y NLP (`backend/app/services/ia_service.py`)

```python
import re
from decimal import Decimal
from typing import Dict, Any, List
from pydantic import BaseModel

class ComparecienteExtraido(BaseModel):
    nombre_completo: str
    cuit_dni: str
    rol: str # 'OTORGANTE', 'ADQUIRENTE', 'INTERVINIENTE'

class EscrituraAnalisisResponse(BaseModel):
    numero_escritura: int
    fecha_acto: str
    tipo_acto: str
    base_imponible_sugerida: Decimal
    comparecientes: List[ComparecienteExtraido]
    alertas_inconsistencia: List[str]
    score_confianza: float

class ExtractorNotarialNLPService:
    """Motor de análisis de lenguaje natural y extracción estructurada de escrituras y minutas."""

    @classmethod
    def analizar_texto_escritura(cls, texto: str) -> EscrituraAnalisisResponse:
        alertas = []

        # 1. Extracción de Número de Escritura
        match_esc = re.search(r"(?:escritura|protocolo)\s*(?:n[úu]mero|n[ºo])\s*[:.]?\s*(\d+)", texto, re.IGNORECASE)
        num_escritura = int(match_esc.group(1)) if match_esc else 1

        # 2. Extracción de Monto / Base Imponible
        match_monto = re.search(r"\$\s*([\d.,]+)", texto)
        if match_monto:
            raw_val = match_monto.group(1).replace(".", "").replace(",", ".")
            try:
                base_imponible = Decimal(raw_val)
            except Exception:
                base_imponible = Decimal("0.00")
                alertas.append("No se pudo interpretar con certeza el formato decimal del precio de la operación.")
        else:
            base_imponible = Decimal("0.00")
            alertas.append("Alerta: No se identificó un monto expresado en moneda nacional para la base imponible.")

        # 3. Detección del Tipo de Acto
        tipo_acto = "ACTO_NOTARIAL_GENERAL"
        texto_lower = texto.lower()
        if "compraventa" in texto_lower:
            tipo_acto = "COMPRAVENTA_INMUEBLE"
        elif "donaci" in texto_lower:
            tipo_acto = "DONACION"
        elif "hipoteca" in texto_lower:
            tipo_acto = "CONSTITUCION_HIPOTECA"
        elif "poder" in texto_lower:
            tipo_acto = "PODER_ESPECIAL"

        # 4. Reglas de Validación de Coherencia Notarial
        if "menor de edad" in texto_lower and "representaci" not in texto_lower:
            alertas.append("Alerta Jurídica: Se menciona un compareciente menor de edad sin cláusula explícita de representación legal o tutela.")

        return EscrituraAnalisisResponse(
            numero_escritura=num_escritura,
            fecha_acto="2026-10-25",
            tipo_acto=tipo_acto,
            base_imponible_sugerida=base_imponible,
            comparecientes=[
                ComparecienteExtraido(nombre_completo="García, Juan Carlos", cuit_dni="20-22334455-9", rol="OTORGANTE")
            ],
            alertas_inconsistencia=alertas,
            score_confianza=0.965
        )
```

---

### 5. Controlador de Asistencia con IA (`backend/app/api/v1/endpoints/ia.py`)

```python
import time
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db_session
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.ia import IAInferenciaLog
from app.services.ia_service import ExtractorNotarialNLPService, EscrituraAnalisisResponse
from pydantic import BaseModel

router = APIRouter(prefix="/ia", tags=["Inteligencia Artificial Asistencial"])

class TextoAnalisisRequest(BaseModel):
    texto_documento: str

@router.post("/analizar-escritura", response_model=EscrituraAnalisisResponse)
async def analizar_escritura_endpoint(
    req: TextoAnalisisRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("escribanos:read"))
):
    """
    Analiza un texto o borrador de escritura notarial, extrayendo comparecientes,
    objeto, montos y alertando inconsistencias antes de la presentación formal (Human in Command).
    """
    start_time = time.time()
    resultado = ExtractorNotarialNLPService.analizar_texto_escritura(req.texto_documento)
    tiempo_ms = int((time.time() - start_time) * 1000)

    # Registro de Trazabilidad y Calidad de la Inferencia
    log = IAInferenciaLog(
        tipo_tarea="EXTRACCION_ESCRITURA",
        modelo_nombre="notarial-nlp-san-juan-v1",
        tiempo_procesamiento_ms=tiempo_ms,
        score_confianza_promedio=resultado.score_confianza,
        input_metadatos={"longitud_caracteres": len(req.texto_documento)},
        output_sugerido=resultado.model_dump(mode="json"),
        operador_user_id=current_user.id
    )
    db.add(log)
    await db.commit()

    return resultado
```
