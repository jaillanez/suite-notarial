# Documento de Ingeniería de Software — Módulo 4
## Motor Paramétrico de Aportes y Reglas de Negocio Previsionales
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Requerimientos del Pliego:** `PAR-01`, `PAR-02`, `PAR-03`, `PAR-04`, `SEC-01`, `SEC-03`  
**Stack de Referencia:** Python 3.12+ | FastAPI | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 (Decimal) | React + TypeScript

> **Implementación (Fase 3).** Diferencias con el texto de abajo, que prevalecen (manda `AGENTS.md`):
>
> - **Porcentajes en %** (`1.5000` = 1,5 %) en `Numeric(18,4)`, no como fracción en `Numeric(6,4)`:
>   se leen igual que en las resoluciones y admiten alícuotas de hasta cuatro decimales de %.
> - **Valores según el tipo:** porcentual (porcentaje, mínimo, tope), fijo mensual (monto) y mora
>   (tasa mensual, días de gracia); la API rechaza campos que no corresponden al tipo.
> - **Sin solapamiento garantizado por la base** (restricción de exclusión GiST) y **valores
>   inmutables por trigger**. Estados: `PENDIENTE_APROBACION`, `VIGENTE`, `RECHAZADA` (no hay
>   REEMPLAZADO/ANULADO: una vigencia reemplazada sigue VIGENTE en su rango, cerrado con fecha).
> - **Cuatro ojos:** quien propone no puede aprobar (API + CHECK en la base). Permiso
>   `parameters:approve` para `ROLE_ADMIN`.
> - **Auditoría** en `audit_security_logs` (actor, UTC, IP, valor anterior y nuevo), sin la tabla
>   `parametros_auditoria_log` aparte.
> - **Fechas de consulta** en hora de San Juan, no del servidor.
> - **Mora:** se implementó la fórmula de §3 (interés simple, tasa mensual / 30 por día), marcada
>   `TODO(negocio)` junto con desde cuándo corre (vencimiento o fin de la gracia).
> - **Rutas:** `/api/v1/parametros/{conceptos, conceptos/{id}/vigencias, vigencias/{id}/aprobar,
>   vigencias/{id}/rechazar, simulacion}`.

---

### 1. Propósito, Alcance y Mitigación de Defectos Previos

El **Módulo 4 (Motor Paramétrico de Aportes)** constituye el núcleo normativo y financiero de la suite. Centraliza, versiona y ejecuta el catálogo de fórmulas, alícuotas, aportes fijos, escalas arancelarias y tasas de mora aplicables sobre las declaraciones juradas de los escribanos.

#### 1.1 Reglas de Dominio y Mitigación de Defectos
1. **Inmutabilidad y Preservación Histórica de Boletas (`PAR-03`):** Ninguna modificación en los parámetros previsionales (por ejemplo, incremento en la alícuota sobre escrituras o actualización del aporte asistencial) puede alterar de manera silenciosa ni retroactiva las boletas de pago ya emitidas ni las liquidaciones cerradas. Cada boleta emitida queda indisolublemente vinculada al ID de la versión paramétrica vigente al momento de su cálculo, conservando una fotografía exacta (*snapshot*) de los factores aplicados.
2. **Precisión Numérica Absoluta (`PAR-02`):** Se prohíbe el uso de tipos `float` tanto en la base de datos como en Python. Todo cálculo de alícuotas, importes fijos, intereses y mínimos/máximos se realiza mediante el tipo `Decimal` en Python y `Numeric(18, 4)` o `Numeric(15, 2)` en PostgreSQL.
3. **Control de Vigencias Temporales (`PAR-01`):** Cada parámetro define obligatoriamente un rango de fechas (`fecha_vigencia_desde` y `fecha_vigencia_hasta`). El motor selecciona automáticamente la regla correspondiente según la fecha efectiva del acto notarial o período devengado.
4. **Circuito de Doble Aprobación y Auditoría Inmutable (`PAR-04` / `SEC-03`):** La creación o modificación de una regla paramétrica queda en estado `PENDIENTE_APROBACION` hasta ser refrendada por el Directorio o usuario con permiso `parameters:approve`, registrando autor, fecha UTC, motivo fundado, valor anterior y nuevo.

---

### 2. Modelo de Datos Relacional (PostgreSQL DDL)

```sql
CREATE TABLE IF NOT EXISTS parametros_conceptos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo VARCHAR(50) UNIQUE NOT NULL, -- EJ: 'APORTE_JUBILATORIO', 'FONDO_ASISTENCIAL', 'TASA_MORA'
    nombre VARCHAR(150) NOT NULL,
    tipo_concepto VARCHAR(30) NOT NULL, -- 'PORCENTUAL_ACTO', 'FIJO_MENSUAL', 'TASA_INTERES', 'ESCALA'
    descripcion TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS parametros_vigencias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concepto_id UUID NOT NULL REFERENCES parametros_conceptos(id) ON DELETE RESTRICT,
    version INT NOT NULL DEFAULT 1,
    fecha_vigencia_desde DATE NOT NULL,
    fecha_vigencia_hasta DATE, -- NULL indica vigencia activa e indefinida
    
    -- Valores Cuantitativos (Precisión Decimal Exacta)
    porcentaje NUMERIC(6, 4) DEFAULT 0.0000, -- Ej: 0.0400 para 4%
    monto_fijo NUMERIC(15, 2) DEFAULT 0.00,
    monto_minimo NUMERIC(15, 2) DEFAULT 0.00,
    monto_maximo NUMERIC(15, 2), -- NULL si no tiene tope superior
    tasa_interes_mensual_mora NUMERIC(6, 4) DEFAULT 0.0000, -- Ej: 0.0350 para 3.5%
    dias_gracia_vencimiento INT NOT NULL DEFAULT 10,
    regla_redondeo VARCHAR(20) NOT NULL DEFAULT 'HALF_UP', -- 'HALF_UP', 'FLOOR', 'CEIL'
    
    -- Gobernanza y Estado (PAR-04)
    estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE_APROBACION', -- PENDIENTE_APROBACION, VIGENTE, REEMPLAZADO, ANULADO
    resolucion_respaldo VARCHAR(100) NOT NULL, -- Número de Resolución de Directorio
    motivo_modificacion TEXT NOT NULL,
    aprobado_por_user_id UUID REFERENCES security_users(id),
    fecha_aprobacion TIMESTAMPTZ,
    
    -- Auditoría Base
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_user_id UUID NOT NULL REFERENCES security_users(id)
);

CREATE INDEX idx_param_vigencias_concepto_fechas 
ON parametros_vigencias(concepto_id, fecha_vigencia_desde, fecha_vigencia_hasta);

-- Tabla de Auditoría Inmutable de Parámetros (PAR-04 / SEC-03)
CREATE TABLE IF NOT EXISTS parametros_auditoria_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parametro_vigencia_id UUID NOT NULL REFERENCES parametros_vigencias(id),
    accion VARCHAR(50) NOT NULL, -- CREACION, APROBACION, REEMPLAZO, ANULACION
    valores_anteriores JSONB,
    valores_nuevos JSONB NOT NULL,
    motivo TEXT NOT NULL,
    operador_user_id UUID NOT NULL REFERENCES security_users(id),
    fecha_evento TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    ip_origen VARCHAR(45) NOT NULL
);
```

---

### 3. Motor de Cálculo Financiero y Esquemas Pydantic v2

```python
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEIL
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator

class ParametroVigenciaCreate(BaseModel):
    concepto_id: str
    fecha_vigencia_desde: date
    fecha_vigencia_hasta: Optional[date] = None
    porcentaje: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0.0000"), le=Decimal("1.0000"))
    monto_fijo: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    monto_minimo: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    monto_maximo: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"))
    tasa_interes_mensual_mora: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0.0000"))
    dias_gracia_vencimiento: int = Field(default=10, ge=0, le=90)
    regla_redondeo: str = Field(default="HALF_UP")
    resolucion_respaldo: str = Field(..., min_length=3)
    motivo_modificacion: str = Field(..., min_length=5)

    @model_validator(mode="after")
    def validate_coherence(self):
        if self.monto_maximo is not None and self.monto_minimo > self.monto_maximo:
            raise ValueError("El monto mínimo no puede superar el monto máximo establecido (PAR-02).")
        if self.fecha_vigencia_hasta and self.fecha_vigencia_desde > self.fecha_vigencia_hasta:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")
        return self

class MotorCalculoAportes:
    """Motor de cálculo de alta precisión financiera para liquidaciones previsionales."""
    
    @staticmethod
    def redondear(monto: Decimal, regla: str = "HALF_UP") -> Decimal:
        modo = ROUND_HALF_UP
        if regla == "FLOOR":
            modo = ROUND_FLOOR
        elif regla == "CEIL":
            modo = ROUND_CEIL
        return monto.quantize(Decimal("0.01"), rounding=modo)

    @classmethod
    def calcular_renglon_acto(
        cls,
        base_imponible: Decimal,
        alicuota_porcentual: Decimal,
        minimo: Decimal,
        maximo: Optional[Decimal],
        regla_redondeo: str = "HALF_UP"
    ) -> Decimal:
        calculo_bruto = base_imponible * alicuota_porcentual
        
        # Aplicación de Escalas y Topes
        if calculo_bruto < minimo:
            resultado = minimo
        elif maximo is not None and calculo_bruto > maximo:
            resultado = maximo
        else:
            resultado = calculo_bruto
            
        return cls.redondear(resultado, regla_redondeo)

    @classmethod
    def calcular_interes_mora(
        cls,
        monto_original: Decimal,
        dias_mora: int,
        tasa_mensual: Decimal,
        regla_redondeo: str = "HALF_UP"
    ) -> Decimal:
        if dias_mora <= 0 or tasa_mensual <= Decimal("0.0000"):
            return Decimal("0.00")
            
        # Tasa diaria lineal exacta = tasa_mensual / 30
        tasa_diaria = tasa_mensual / Decimal("30")
        interes_devengado = monto_original * tasa_diaria * Decimal(str(dias_mora))
        return cls.redondear(interes_devengado, regla_redondeo)
```

---

### 4. Controlador de Parámetros (`backend/app/api/v1/endpoints/parametros.py`)

```python
import uuid
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.core.database import get_db_session
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.parametros import ParametroConcepto, ParametroVigencia, ParametroAuditoriaLog
from app.schemas.parametros import ParametroVigenciaCreate, ParametroVigenciaResponse

router = APIRouter(prefix="/parametros", tags=["Parámetros Previsionales"])

@router.get("/activos", response_model=List[ParametroVigenciaResponse])
async def get_parametros_vigentes(
    fecha: Optional[date] = None,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("parameters:read"))
):
    fecha_consulta = fecha or date.today()
    stmt = select(ParametroVigencia).where(
        and_(
            ParametroVigencia.estado == "VIGENTE",
            ParametroVigencia.fecha_vigencia_desde <= fecha_consulta,
            or_(
                ParametroVigencia.fecha_vigencia_hasta.is_(None),
                ParametroVigencia.fecha_vigencia_hasta >= fecha_consulta
            )
        )
    )
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/vigencias", status_code=status.HTTP_201_CREATED)
async def create_parametro_vigencia(
    payload: ParametroVigenciaCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("parameters:write"))
):
    nueva_vigencia = ParametroVigencia(
        concepto_id=uuid.UUID(payload.concepto_id),
        fecha_vigencia_desde=payload.fecha_vigencia_desde,
        fecha_vigencia_hasta=payload.fecha_vigencia_hasta,
        porcentaje=payload.porcentaje,
        monto_fijo=payload.monto_fijo,
        monto_minimo=payload.monto_minimo,
        monto_maximo=payload.monto_maximo,
        tasa_interes_mensual_mora=payload.tasa_interes_mensual_mora,
        dias_gracia_vencimiento=payload.dias_gracia_vencimiento,
        regla_redondeo=payload.regla_redondeo,
        resolucion_respaldo=payload.resolucion_respaldo,
        motivo_modificacion=payload.motivo_modificacion,
        estado="PENDIENTE_APROBACION",
        created_by_user_id=current_user.id
    )
    db.add(nueva_vigencia)
    await db.flush()

    audit = ParametroAuditoriaLog(
        parametro_vigencia_id=nueva_vigencia.id,
        accion="CREACION_PROPUESTA",
        valores_nuevos=payload.model_dump(mode="json"),
        motivo=payload.motivo_modificacion,
        operador_user_id=current_user.id,
        ip_origen=request.client.host if request.client else "unknown"
    )
    db.add(audit)
    await db.commit()

    return {"status": "success", "id": nueva_vigencia.id, "message": "Parámetro registrado pendiente de aprobación."}

@router.post("/vigencias/{vigencia_id}/aprobar", status_code=status.HTTP_200_OK)
async def aprobar_parametro_vigencia(
    vigencia_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("parameters:approve"))
):
    stmt = select(ParametroVigencia).where(ParametroVigencia.id == vigencia_id)
    vigencia = (await db.execute(stmt)).scalar_one_or_none()
    
    if not vigencia:
        raise HTTPException(status_code=404, detail="Parámetro no encontrado.")
    if vigencia.estado != "PENDIENTE_APROBACION":
        raise HTTPException(status_code=400, detail="El parámetro no se encuentra pendiente de aprobación.")

    vigencia.estado = "VIGENTE"
    vigencia.aprobado_por_user_id = current_user.id
    vigencia.fecha_aprobacion = datetime.now()

    audit = ParametroAuditoriaLog(
        parametro_vigencia_id=vigencia.id,
        accion="APROBACION_DIRECTORIO",
        valores_nuevos={"estado": "VIGENTE", "aprobado_por": str(current_user.id)},
        motivo=f"Aprobación formal según Resolución {vigencia.resolucion_respaldo}",
        operador_user_id=current_user.id,
        ip_origen=request.client.host if request.client else "unknown"
    )
    db.add(audit)
    await db.commit()

    return {"status": "success", "message": "Parámetro aprobado y puesto en vigencia (PAR-04)."}
```
