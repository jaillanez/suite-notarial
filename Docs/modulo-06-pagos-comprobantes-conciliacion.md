# Documento de Ingeniería de Software — Módulo 6
## Gestión de Pagos, Comprobantes y Conciliación de Tesorería
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Requerimientos del Pliego:** `DDJJ-04`, `DDJJ-05`, `DDJJ-06`, `DDJJ-07`, `SEC-01`, `SEC-03`, `SEC-07`  
**Stack de Referencia:** Python 3.12+ | FastAPI | python-magic | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 | React + TypeScript

> **Implementación (Fase 5).** Diferencias con el texto de abajo, que prevalecen (manda `AGENTS.md`):
>
> - **Estados:** comprobante `PENDIENTE_REVISION`, `APROBADO`, `RECHAZADO`; boleta `PENDIENTE`,
>   `PAGADA`, `ANULADA` (Fase 4). No hay estado financiero aparte: el estado de la boleta y el de
>   su último comprobante lo cubren (`VENCIDA` se deduce de la fecha).
> - **Archivo:** tipo por *magic bytes* sobre el contenido (PDF, PNG, JPEG), máximo
>   `MAX_UPLOAD_MB` controlado mientras se lee, nombre UUID bajo
>   `UPLOAD_DIR/comprobantes/AAAA/MM/`, permisos 0600 y creación exclusiva. La huella SHA-256 se
>   verifica cada vez que se sirve; si no coincide se audita como CRITICAL y no se entrega.
> - **Un comprobante en revisión por boleta** (índice único parcial); rechazado, se puede
>   adjuntar otro. Mientras haya uno en revisión, la boleta no se reemite ni se rectifica.
> - **Aprobación:** Tesorería tipea el importe y la fecha de acreditación del extracto (no se
>   precargan). Solo se aprueba el total exacto de la boleta; acreditación posterior a la fecha de
>   pago exige observaciones. `TODO(negocio)`: pagos parciales o con diferencia y la mora por
>   acreditación tardía. Quien adjuntó no puede revisar.
> - **Asiento inmutable** en `pagos_conciliaciones` (aprobación o rechazo; sin UPDATE/DELETE para
>   la aplicación). Un trigger impide pasar una boleta a `PAGADA` sin un asiento aprobado.
> - **Rechazo con motivo** obligatorio y aviso por correo al escribano (también al aprobar), con
>   enlace desde `PUBLIC_WEB_URL`.
> - **Cuenta recaudadora** por configuración (`BANCO_*`, Fase 4), sin tabla de cuentas
>   bancarias: hay una sola. `TODO(negocio)` si la Caja recauda en más de una.
> - **Rutas:** `/api/v1/pagos/{boletas/{id}/comprobantes, comprobantes, comprobantes/{id},
>   comprobantes/{id}/archivo, comprobantes/{id}/aprobar, comprobantes/{id}/rechazar}`.

---

### 1. Propósito, Alcance y Mitigación de Defectos Críticos

El **Módulo 6 (Pagos, Comprobantes y Conciliación)** resuelve el circuito financiero de cancelación de boletas previsionales mediante transferencia bancaria o depósito, asegurando la verificación estricta de comprobantes aportados y proveyendo a la Tesorería una mesa de conciliación inalterable.

#### 1.1 Mitigación Directa de Hallazgos Previos
1. **Desacoplamiento Estricto de Estados (`DDJJ-05`):** Se elimina el defecto operativo donde un estado como "comprobante adjunto" era interpretado erróneamente por el sistema o por el escribano como "pago confirmado". La plataforma maneja una máquina de estados independiente:
   * **Estado de Boleta:** `PENDIENTE`, `PAGADA`, `VENCIDA`, `ANULADA`.
   * **Estado del Comprobante:** `SIN_COMPROBANTE`, `ADJUNTO_PENDIENTE_REVISION`, `APROBADO`, `RECHAZADO`.
   * **Estado Financiero:** `IMPAGO`, `EN_CONCILIACION`, `CANCELADO_TOTAL`, `PAGO_PARCIAL`.
2. **Validación Exhaustiva de Archivos (`DDJJ-04` / `SEC-07`):**
   * Validación del tipo MIME real mediante análisis de cabeceras binarias (*magic bytes*) con `python-magic`, impidiendo que archivos ejecutables (`.exe`, `.sh`, `.php`) sean renombrados a `.pdf` o `.jpg`.
   * Límite estricto de tamaño (máximo 10 MB).
   * Generación de nombres de archivo seguros aleatorios (UUID v4) y almacenamiento fuera del árbol web público ejecutable.
3. **Mesa de Revisión y Conciliación de Tesorería (`DDJJ-06`):** Interfaz para el operador de tesorería con visor integrado de comprobantes, cotejo con extracto bancario y botones de acción unívocos:
   * **Confirmar Pago:** Cambia el comprobante a `APROBADO`, la boleta a `PAGADA` y genera el asiento de conciliación.
   * **Rechazar Comprobante:** Cambia el comprobante a `RECHAZADO`, exige el ingreso obligatorio del motivo (ej. "Transferencia ilegible", "Importe no coincide", "Fecha fuera de término") y notifica inmediatamente al escribano para subsanar.

---

### 2. Modelo de Datos Relacional (PostgreSQL DDL)

```sql
-- Tabla de Cuentas Bancarias Habilitadas para Recaudación
CREATE TABLE IF NOT EXISTS tesoreria_cuentas_bancarias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    banco_nombre VARCHAR(100) NOT NULL, -- Ej: 'Banco de San Juan'
    tipo_cuenta VARCHAR(50) NOT NULL DEFAULT 'CUENTA_CORRIENTE',
    cbu VARCHAR(22) UNIQUE NOT NULL,
    alias VARCHAR(50) UNIQUE NOT NULL,
    cuit_titular VARCHAR(11) NOT NULL,
    instrucciones_pago TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

-- Tabla de Comprobantes Adjuntos por los Escribanos (DDJJ-04)
CREATE TABLE IF NOT EXISTS pagos_comprobantes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    boleta_id UUID NOT NULL REFERENCES boletas_pago(id) ON DELETE RESTRICT,
    escribano_id UUID NOT NULL REFERENCES padron_escribanos(id) ON DELETE RESTRICT,
    
    -- Metadatos del Archivo Físico
    nombre_archivo_original VARCHAR(255) NOT NULL,
    nombre_archivo_almacenado VARCHAR(255) UNIQUE NOT NULL,
    ruta_almacenamiento VARCHAR(500) NOT NULL,
    mime_type_real VARCHAR(100) NOT NULL,
    tamano_bytes BIGINT NOT NULL,
    hash_sha256 VARCHAR(64) NOT NULL,
    
    -- Datos de la Transacción Declarada por el Escribano
    fecha_transferencia DATE NOT NULL,
    banco_origen VARCHAR(100),
    numero_operacion_bancaria VARCHAR(100) NOT NULL,
    importe_declarado NUMERIC(15, 2) NOT NULL,
    cuenta_destino_id UUID REFERENCES tesoreria_cuentas_bancarias(id),
    
    -- Estado de la Revisión (DDJJ-05)
    estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE_REVISION', -- PENDIENTE_REVISION, APROBADO, RECHAZADO
    motivo_rechazo TEXT,
    
    -- Auditoría de Carga
    fecha_carga TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    subido_por_user_id UUID NOT NULL REFERENCES security_users(id)
);

CREATE INDEX idx_comprobantes_boleta ON pagos_comprobantes(boleta_id);
CREATE INDEX idx_comprobantes_estado ON pagos_comprobantes(estado);

-- Tabla de Asientos de Conciliación de Tesorería (DDJJ-06 / SEC-03)
CREATE TABLE IF NOT EXISTS tesoreria_conciliaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comprobante_id UUID NOT NULL REFERENCES pagos_comprobantes(id) ON DELETE RESTRICT,
    boleta_id UUID NOT NULL REFERENCES boletas_pago(id) ON DELETE RESTRICT,
    resultado_conciliacion VARCHAR(30) NOT NULL, -- 'APROBADO', 'RECHAZADO'
    
    -- Verificación Financiera
    importe_confirmado NUMERIC(15, 2) NOT NULL,
    fecha_acreditacion_bancaria DATE NOT NULL,
    identificador_extracto_bancario VARCHAR(100),
    
    -- Auditoría Inmutable
    observaciones TEXT,
    operador_tesoreria_id UUID NOT NULL REFERENCES security_users(id),
    fecha_conciliacion TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    ip_operador VARCHAR(45) NOT NULL
);

CREATE INDEX idx_conciliaciones_boleta ON tesoreria_conciliaciones(boleta_id);
```

---

### 3. Validador de Seguridad de Archivos y Esquemas Pydantic v2

```python
import os
import uuid
import hashlib
from decimal import Decimal
from datetime import date
from typing import Optional
from fastapi import UploadFile, HTTPException, status
import magic
from pydantic import BaseModel, Field

ALLOWED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png"
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 Megabytes

async def validar_y_almacenar_comprobante(
    file: UploadFile,
    storage_directory: str = "/var/caja_notarial/uploads/comprobantes"
) -> dict:
    """
    Inspecciona los magic bytes del archivo en memoria, calcula el hash SHA-256,
    valida extensiones permitidas y almacena bajo nombre seguro UUID (DDJJ-04 / SEC-07).
    """
    # 1. Leer encabezado inicial para análisis de número mágico
    header = await file.read(2048)
    if not header:
        raise HTTPException(status_code=400, detail="El archivo adjunto está vacío.")

    # 2. Detección MIME real en servidor
    mime_detector = magic.Magic(mime=True)
    real_mime = mime_detector.from_buffer(header)

    if real_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Formato no permitido: '{real_mime}'. Únicamente se admiten archivos PDF, JPEG o PNG (DDJJ-04)."
        )

    # 3. Leer archivo completo y calcular SHA-256
    await file.seek(0)
    file_bytes = await file.read()
    total_size = len(file_bytes)

    if total_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera el tamaño máximo permitido de 10 MB (Tamaño actual: {total_size / (1024*1024):.2f} MB)."
        )

    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
    extension = ALLOWED_MIME_TYPES[real_mime]
    secure_filename = f"{uuid.uuid4().hex}{extension}"

    os.makedirs(storage_directory, exist_ok=True)
    destination_path = os.path.join(storage_directory, secure_filename)

    with open(destination_path, "wb") as f:
        f.write(file_bytes)

    return {
        "original_filename": file.filename or "comprobante",
        "stored_filename": secure_filename,
        "storage_path": destination_path,
        "mime_type": real_mime,
        "size_bytes": total_size,
        "sha256": sha256_hash
    }

class ConciliacionRequest(BaseModel):
    accion: str = Field(..., pattern="^(APROBAR|RECHAZAR)$")
    importe_confirmado: Optional[Decimal] = Field(None, ge=Decimal("0.00"))
    fecha_acreditacion: Optional[date] = None
    identificador_extracto: Optional[str] = None
    motivo_rechazo: Optional[str] = None
```

---

### 4. Controlador de Carga y Conciliación (`backend/app/api/v1/endpoints/pagos.py`)

```python
import uuid
from decimal import Decimal
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db_session
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.ddjj import BoletaPago
from app.models.pagos import PagoComprobante, TesoreriaConciliacion
from app.schemas.pagos import ConciliacionRequest

router = APIRouter(prefix="/pagos", tags=["Comprobantes y Conciliación"])

@router.post("/comprobantes/upload", status_code=status.HTTP_201_CREATED)
async def upload_comprobante(
    boleta_id: uuid.UUID = Form(...),
    fecha_transferencia: date = Form(...),
    numero_operacion: str = Form(...),
    importe_declarado: Decimal = Form(...),
    banco_origen: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("comprobantes:upload"))
):
    stmt_boleta = select(BoletaPago).where(BoletaPago.id == boleta_id)
    boleta = (await db.execute(stmt_boleta)).scalar_one_or_none()

    if not boleta:
        raise HTTPException(status_code=404, detail="Boleta de pago no encontrada.")
    if boleta.estado == "PAGADA":
        raise HTTPException(status_code=400, detail="La boleta seleccionada ya ha sido cancelada.")

    file_meta = await validar_y_almacenar_comprobante(file)

    comprobante = PagoComprobante(
        boleta_id=boleta.id,
        escribano_id=boleta.escribano_id,
        nombre_archivo_original=file_meta["original_filename"],
        nombre_archivo_almacenado=file_meta["stored_filename"],
        ruta_almacenamiento=file_meta["storage_path"],
        mime_type_real=file_meta["mime_type"],
        tamano_bytes=file_meta["size_bytes"],
        hash_sha256=file_meta["sha256"],
        fecha_transferencia=fecha_transferencia,
        banco_origen=banco_origen,
        numero_operacion_bancaria=numero_operacion,
        importe_declarado=importe_declarado,
        estado="PENDIENTE_REVISION",
        subido_por_user_id=current_user.id
    )
    db.add(comprobante)
    await db.commit()

    return {
        "status": "success",
        "message": "Comprobante recibido y registrado pendiente de verificación por Tesorería (DDJJ-05).",
        "comprobante_id": comprobante.id,
        "estado_comprobante": comprobante.estado
    }

@router.post("/comprobantes/{comprobante_id}/conciliar", status_code=status.HTTP_200_OK)
async def conciliar_comprobante(
    comprobante_id: uuid.UUID,
    payload: ConciliacionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("comprobantes:verify"))
):
    stmt_comp = select(PagoComprobante).where(PagoComprobante.id == comprobante_id)
    comprobante = (await db.execute(stmt_comp)).scalar_one_or_none()

    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado.")
    if comprobante.estado != "PENDIENTE_REVISION":
        raise HTTPException(status_code=400, detail=f"El comprobante ya fue procesado con estado {comprobante.estado}.")

    stmt_bol = select(BoletaPago).where(BoletaPago.id == comprobante.boleta_id)
    boleta = (await db.execute(stmt_bol)).scalar_one()

    ip_operador = request.client.host if request.client else "unknown"

    if payload.accion == "APROBAR":
        if not payload.fecha_acreditacion:
            raise HTTPException(status_code=400, detail="Debe especificar la fecha de acreditación bancaria.")

        comprobante.estado = "APROBADO"
        boleta.estado = "PAGADA"

        conciliacion = TesoreriaConciliacion(
            comprobante_id=comprobante.id,
            boleta_id=boleta.id,
            resultado_conciliacion="APROBADO",
            importe_confirmado=payload.importe_confirmado or comprobante.importe_declarado,
            fecha_acreditacion_bancaria=payload.fecha_acreditacion,
            identificador_extracto_bancario=payload.identificador_extracto,
            operador_tesoreria_id=current_user.id,
            ip_operador=ip_operador
        )
        db.add(conciliacion)
        await db.commit()

        return {"status": "success", "message": "Pago verificado y boleta cancelada exitosamente (DDJJ-06)."}

    else: # RECHAZAR
        if not payload.motivo_rechazo or len(payload.motivo_rechazo.strip()) < 5:
            raise HTTPException(status_code=400, detail="El motivo de rechazo es obligatorio y debe ser fundamentado.")

        comprobante.estado = "RECHAZADO"
        comprobante.motivo_rechazo = payload.motivo_rechazo

        conciliacion = TesoreriaConciliacion(
            comprobante_id=comprobante.id,
            boleta_id=boleta.id,
            resultado_conciliacion="RECHAZADO",
            importe_confirmado=Decimal("0.00"),
            fecha_acreditacion_bancaria=date.today(),
            observaciones=payload.motivo_rechazo,
            operador_tesoreria_id=current_user.id,
            ip_operador=ip_operador
        )
        db.add(conciliacion)
        await db.commit()

        return {
            "status": "rejected",
            "message": "Comprobante rechazado. Se ha notificado al escribano para su corrección.",
            "motivo": payload.motivo_rechazo
        }
```
