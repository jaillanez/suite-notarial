# Documento de Ingeniería de Software — Módulo 5
## Declaraciones Juradas (DDJJ), Liquidación de Protocolos y Boletas de Pago
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Requerimientos del Pliego:** `DDJJ-01`, `DDJJ-02`, `DDJJ-03`, `DDJJ-05`, `PAR-02`, `PAR-03`, `SEC-01`, `SEC-03`  
**Stack de Referencia:** Python 3.12+ | FastAPI | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 | ReportLab / WeasyPrint (PDF) | React + TypeScript

> **Implementación (Fase 4).** Diferencias con el texto de abajo, que prevalecen (manda `AGENTS.md`):
>
> - **Controles del libro de protocolo:** número de escritura único por registro, protocolo y año
>   (bloquea), salvo los actos múltiples de una misma escritura (misma DDJJ y fecha, un aporte
>   por acto, columna `orden_en_escritura`), folio repetido o fuera de orden y fecha fuera de orden (avisan), números salteados
>   del año en la ficha. `TODO(negocio)`: confirmar que la numeración se reinicia cada año.
> - **Una DDJJ por registro notarial y período**, no por escribano: reúne los actos de titular,
>   adscriptos y escribanos a cargo, como en el sistema en uso. Cada acto guarda el escribano y su
>   cargo a la fecha del acto.
> - **Categorías de acto** relevadas del sistema actual: escritura con valor (porcentaje sobre la
>   base con mínimo y tope), acta o poder y otro acto (montos fijos) y sin efecto (no aporta).
> - **Liquidación** (`app/modules/ddjj/liquidacion.py`, reproduce la boleta 1069 de 09/2026):
>   excedente = máx(0, protocolos − aporte mínimo mensual); total en término = mínimo + excedente +
>   aporte médico (uno por titular o adscripto con cargo en el período); interés de mora sobre el
>   total en término con la tasa vigente al vencimiento. `TODO(negocio)` en cada supuesto.
> - **Vigencias al primer día del período** (mes devengado). Al presentar se congelan el aporte y
>   la vigencia de cada acto, y la boleta guarda las del mínimo, el médico y la mora (SNAP).
> - **Calendario de vencimientos** por período (`ddjj_vencimientos`), cargado por Administración;
>   el de un período con boletas ya no se puede cambiar (trigger).
> - **Estados:** DDJJ `BORRADOR`, `PRESENTADA`, `RECTIFICADA`; boleta `PENDIENTE`, `PAGADA`,
>   `ANULADA` (sin `CERRADA` ni `VENCIDA`: el vencimiento se ve por fecha y lo usa la Fase 5).
> - **Boleta** con número correlativo (secuencia), código de verificación base32 de 16 caracteres,
>   huella SHA-256 de los datos impresos, QR a `PUBLIC_WEB_URL/verificar/{codigo}` y Code128. Una
>   boleta nueva para otra fecha de pago anula la pendiente y solo recalcula la mora.
> - **Inmutabilidad en la base:** sin DELETE/TRUNCATE; actos solo con la DDJJ en borrador; una
>   DDJJ presentada solo pasa a rectificada; una boleta solo cambia de estado.
> - **Acceso:** el escribano opera las DDJJ de los registros donde tiene cargo vigente y consulta
>   las de los meses en que lo tuvo; la Caja consulta y carga cualquiera (`ddjj:approve`).
> - **Rutas:** `/api/v1/ddjj/{registros, vencimientos, declaraciones, declaraciones/{id}/actos,
>   liquidacion, presentar, boletas, rectificar}`, `/api/v1/ddjj/boletas/{id}[/pdf]` y la
>   pública `/api/v1/boletas/verificar/{codigo}`.

---

### 1. Propósito, Alcance y Circuito Operativo

El **Módulo 5 (DDJJ y Boletas de Pago)** gestiona el ciclo de vida de la presentación mensual de escrituras y actos protocolares por parte de los escribanos, calculando automáticamente las obligaciones previsionales y médico-asistenciales y generando las boletas oficiales de pago verificables con código de barras y QR interoperable.

#### 1.1 Reglas del Negocio Previsional Notarial
1. **Cálculo Exclusivo en Servidor (`DDJJ-02` / `SEC-01`):** Queda prohibido calcular importes, alícuotas o subtotales en el frontend React. El cliente solo envía datos estructurados del acto (número de escritura, fecha, base imponible, tipo de acto) y el servidor FastAPI ejecuta la liquidación aplicando las reglas vigentes.
2. **Estructura de la Declaración Jurada Mensual (`DDJJ-01`):** Cada escribano presenta una declaración jurada por cada período fiscal mensual (`YYYY-MM`), detallando cada renglón de escritura protocolar.
3. **Emisión de Boleta con Identificador Único y Código Verificable (`DDJJ-03`):** Toda liquidación confirmada genera una boleta con código alfanumérico único, código de barras estándar (ej. Code 128 / ITF-14) y código QR que apunta a la URL pública de validación de autenticidad.
4. **Desacoplamiento de Estados (`DDJJ-05`):** Se separan rígidamente los estados de la declaración jurada (`BORRADOR`, `PRESENTADA`, `RECTIFICADA`, `CERRADA`) de los estados de la boleta de pago (`PENDIENTE`, `PAGADA`, `VENCIDA`, `ANULADA`).

---

### 2. Modelo de Datos Relacional (PostgreSQL DDL)

```sql
-- Tabla Principal de Declaraciones Juradas Mensuales
CREATE TABLE IF NOT EXISTS ddjj_declaraciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    escribano_id UUID NOT NULL REFERENCES padron_escribanos(id) ON DELETE RESTRICT,
    registro_id UUID NOT NULL REFERENCES padron_registros_notariales(id) ON DELETE RESTRICT,
    periodo VARCHAR(7) NOT NULL, -- Formato 'YYYY-MM'
    numero_rectificativa INT NOT NULL DEFAULT 0,
    
    -- Totales Consolidados (Calculados con Precisión Decimal Exacta)
    cantidad_escrituras INT NOT NULL DEFAULT 0,
    base_imponible_total NUMERIC(18, 2) NOT NULL DEFAULT 0.00,
    total_aporte_previsional NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_fondo_asistencial NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_fijo_mensual NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_liquidado NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    
    -- Estados y Trazabilidad (DDJJ-05)
    estado VARCHAR(30) NOT NULL DEFAULT 'BORRADOR', -- BORRADOR, PRESENTADA, RECTIFICADA, CERRADA
    fecha_presentacion TIMESTAMPTZ,
    presentado_por_user_id UUID REFERENCES security_users(id),
    observaciones TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    
    CONSTRAINT uq_escribano_periodo_rectificativa UNIQUE (escribano_id, periodo, numero_rectificativa)
);

CREATE INDEX idx_ddjj_escribano_periodo ON ddjj_declaraciones(escribano_id, periodo);
CREATE INDEX idx_ddjj_estado ON ddjj_declaraciones(estado);

-- Tabla de Renglones de Escrituras / Actos Declarados
CREATE TABLE IF NOT EXISTS ddjj_renglones_escrituras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ddjj_id UUID NOT NULL REFERENCES ddjj_declaraciones(id) ON DELETE CASCADE,
    numero_escritura INT NOT NULL,
    fecha_escritura DATE NOT NULL,
    tomo VARCHAR(20),
    folio_desde INT NOT NULL,
    folio_hasta INT NOT NULL,
    tipo_acto VARCHAR(100) NOT NULL, -- 'COMPRAVENTA', 'HIPOTECA', 'DONACION', etc.
    descripcion_objeto TEXT,
    
    -- Valores Monetarios y Cálculo Inmutable (PAR-03)
    base_imponible NUMERIC(18, 2) NOT NULL DEFAULT 0.00,
    parametro_vigencia_id UUID NOT NULL REFERENCES parametros_vigencias(id),
    alicuota_aplicada NUMERIC(6, 4) NOT NULL,
    monto_previsional NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    monto_asistencial NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    monto_total_renglon NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_renglones_ddjj ON ddjj_renglones_escrituras(ddjj_id);

-- Tabla de Boletas Oficiales de Pago (DDJJ-03)
CREATE TABLE IF NOT EXISTS boletas_pago (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo_barras VARCHAR(100) UNIQUE NOT NULL,
    numero_boleta VARCHAR(50) UNIQUE NOT NULL, -- Ej: 'BOL-2026-10-00842'
    ddjj_id UUID NOT NULL REFERENCES ddjj_declaraciones(id) ON DELETE RESTRICT,
    escribano_id UUID NOT NULL REFERENCES padron_escribanos(id) ON DELETE RESTRICT,
    periodo VARCHAR(7) NOT NULL,
    
    -- Montos e Importes (Precisión Decimal Exacta)
    monto_original NUMERIC(15, 2) NOT NULL,
    monto_interes_mora NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    monto_total NUMERIC(15, 2) NOT NULL,
    
    -- Fechas Críticas
    fecha_emision DATE NOT NULL DEFAULT CURRENT_DATE,
    fecha_primer_vencimiento DATE NOT NULL,
    fecha_segundo_vencimiento DATE,
    recargo_segundo_vencimiento NUMERIC(15, 2) DEFAULT 0.00,
    
    -- Estados Independientes (DDJJ-05)
    estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE, PAGADA, VENCIDA, ANULADA
    
    -- Hash y Verificación Digital
    checksum_sha256 VARCHAR(64) NOT NULL,
    pdf_storage_path VARCHAR(255),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_boletas_codigo_barras ON boletas_pago(codigo_barras);
CREATE INDEX idx_boletas_escribano ON boletas_pago(escribano_id);
```

---

### 3. Esquemas Pydantic v2 y Generación de PDF

```python
import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class RenglonEscrituraCreate(BaseModel):
    numero_escritura: int = Field(..., gt=0)
    fecha_escritura: date
    tomo: Optional[str] = None
    folio_desde: int = Field(..., gt=0)
    folio_hasta: int = Field(..., gt=0)
    tipo_acto: str = Field(..., min_length=3)
    descripcion_objeto: Optional[str] = None
    base_imponible: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))

class DDJJCreate(BaseModel):
    escribano_id: uuid.UUID
    registro_id: uuid.UUID
    periodo: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Formato YYYY-MM")
    renglones: List[RenglonEscrituraCreate]
    observaciones: Optional[str] = None

class BoletaDetalleResponse(BaseModel):
    id: uuid.UUID
    numero_boleta: str
    codigo_barras: str
    periodo: str
    monto_original: Decimal
    monto_interes_mora: Decimal
    monto_total: Decimal
    fecha_emision: date
    fecha_primer_vencimiento: date
    estado: str
    escribano_nombre: str
    escribano_matricula: int
    url_descarga_pdf: str
```

---

### 4. Controlador de DDJJ y Emisión de Boletas (`backend/app/api/v1/endpoints/ddjj.py`)

```python
import uuid
import hashlib
from datetime import date, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.core.database import get_db_session
from app.core.config import settings
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.padron import Escribano
from app.models.parametros import ParametroVigencia
from app.models.ddjj import DeclaracionJurada, RenglonEscritura, BoletaPago
from app.schemas.ddjj import DDJJCreate, BoletaDetalleResponse

router = APIRouter(prefix="/ddjj", tags=["Declaraciones Juradas y Boletas"])

@router.post("/presentar", status_code=status.HTTP_201_CREATED)
async def presentar_ddjj(
    payload: DDJJCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("ddjj:create_own"))
):
    # 1. Obtener parámetros vigentes para el período
    stmt_param = select(ParametroVigencia).where(
        and_(
            ParametroVigencia.estado == "VIGENTE",
            ParametroVigencia.fecha_vigencia_desde <= date.today()
        )
    ).order_by(ParametroVigencia.fecha_vigencia_desde.desc())
    param_res = await db.execute(stmt_param)
    param_vigente = param_res.scalars().first()

    if not param_vigente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se encontraron parámetros previsionales vigentes para liquidar."
        )

    # 2. Instanciar Declaración Jurada
    ddjj = DeclaracionJurada(
        escribano_id=payload.escribano_id,
        registro_id=payload.registro_id,
        periodo=payload.periodo,
        estado="PRESENTADA",
        fecha_presentacion=datetime.now(),
        presentado_por_user_id=current_user.id,
        observaciones=payload.observaciones
    )
    db.add(ddjj)
    await db.flush()

    total_previsional = Decimal("0.00")
    total_asistencial = Decimal("0.00")
    base_imponible_acumulada = Decimal("0.00")

    # 3. Liquidar cada renglón en el servidor (DDJJ-02)
    for item in payload.renglones:
        aporte_acto = (item.base_imponible * param_vigente.porcentaje).quantize(Decimal("0.01"))
        if aporte_acto < param_vigente.monto_minimo:
            aporte_acto = param_vigente.monto_minimo
        elif param_vigente.monto_maximo and aporte_acto > param_vigente.monto_maximo:
            aporte_acto = param_vigente.monto_maximo

        asistencial_acto = (aporte_acto * Decimal("0.10")).quantize(Decimal("0.01")) # 10% asistencial
        renglon_total = aporte_acto + asistencial_acto

        renglon = RenglonEscritura(
            ddjj_id=ddjj.id,
            numero_escritura=item.numero_escritura,
            fecha_escritura=item.fecha_escritura,
            tomo=item.tomo,
            folio_desde=item.folio_desde,
            folio_hasta=item.folio_hasta,
            tipo_acto=item.tipo_acto,
            descripcion_objeto=item.descripcion_objeto,
            base_imponible=item.base_imponible,
            parametro_vigencia_id=param_vigente.id,
            alicuota_aplicada=param_vigente.porcentaje,
            monto_previsional=aporte_acto,
            monto_asistencial=asistencial_acto,
            monto_total_renglon=renglon_total
        )
        db.add(renglon)

        total_previsional += aporte_acto
        total_asistencial += asistencial_acto
        base_imponible_acumulada += item.base_imponible

    monto_fijo = param_vigente.monto_fijo
    total_general = total_previsional + total_asistencial + monto_fijo

    ddjj.cantidad_escrituras = len(payload.renglones)
    ddjj.base_imponible_total = base_imponible_acumulada
    ddjj.total_aporte_previsional = total_previsional
    ddjj.total_fondo_asistencial = total_asistencial
    ddjj.total_fijo_mensual = monto_fijo
    ddjj.total_liquidado = total_general

    # 4. Generación Inmediata de Boleta de Pago Oficial (DDJJ-03)
    numero_boleta = f"BOL-{payload.periodo}-{str(uuid.uuid4())[:8].upper()}"
    codigo_barras = f"0842{payload.periodo.replace('-', '')}{int(total_general * 100):010d}"
    vencimiento = date.today() + timedelta(days=param_vigente.dias_gracia_vencimiento)

    checksum = hashlib.sha256(f"{numero_boleta}{total_general}{vencimiento}".encode()).hexdigest()

    boleta = BoletaPago(
        codigo_barras=codigo_barras,
        numero_boleta=numero_boleta,
        ddjj_id=ddjj.id,
        escribano_id=payload.escribano_id,
        periodo=payload.periodo,
        monto_original=total_general,
        monto_total=total_general,
        fecha_primer_vencimiento=vencimiento,
        estado="PENDIENTE",
        checksum_sha256=checksum
    )
    db.add(boleta)
    await db.commit()

    return {
        "status": "success",
        "message": "Declaración jurada presentada y liquidada con éxito.",
        "ddjj_id": ddjj.id,
        "boleta_id": boleta.id,
        "numero_boleta": boleta.numero_boleta,
        "total_a_pagar": str(total_general),
        "fecha_vencimiento": vencimiento.isoformat()
    }
```
