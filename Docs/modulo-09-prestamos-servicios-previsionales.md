# Documento de Ingeniería de Software — Módulo 9
## Servicios Previsionales, Préstamos y Beneficios al Afiliado
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Estándares de Referencia:** Cajas de Previsión Social (San Juan, CJPPU, CSSPKPBA) | ISSA Guidelines on Benefit Administration | Ley 18.212 | CCyCN  
**Stack de Referencia:** Python 3.12+ | FastAPI | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 (Decimal) | React + TypeScript

---

### 1. Propósito, Alcance y Reglas de Negocio Financiero-Previsionales

El **Módulo 9 (Servicios Previsionales y Préstamos)** amplía el ecosistema de la Caja Notarial para gestionar una de las prestaciones asistenciales y de inversión de reservas más trascendentes: la concesión y administración de préstamos personales, hipotecarios y de emergencia para afiliados activos y pasivos.

#### 1.1 Reglas del Dominio Financiero Previsional
1. **Líneas de Crédito Paramétricas:**
   * **Línea Ordinaria / Común (Activos):** Plazos de 12 a 36 meses para inversión profesional o consumo.
   * **Línea Recién Matriculados:** Plazos extendidos (hasta 48 o 60 meses) con tasa subsidiada para equipamiento inicial de escribanía.
   * **Línea Pasivos (Jubilados / Pensionados):** Cuotas con débito directo de sus haberes previsionales.
   * **Línea Extraordinaria / Asistencial:** Situaciones de salud o catástrofe documentadas.
2. **Topes de Afectación de Ingresos Netos:** La cuota mensual no puede superar el **25% al 30%** del promedio mensual de ingresos acreditados (o del haber previsional líquido en caso de pasivos), deduciendo previamente retenciones impositivas o deudas preexistentes.
3. **Cálculo de Amortización con Precisión Exacta:** Implementación del **Sistema Francés** (cuota total constante con amortización creciente de capital e interés decreciente sobre saldos) y **Sistema Alemán** (amortización de capital fija con cuota decreciente). Prohibición terminante de cálculos aproximados o tipos `float`.
4. **Tasas de Interés y Regulación de Usura:** Las tasas nominales y efectivas anuales se fijan mensualmente por Directorio vinculadas a la tasa testigo bancaria oficial (Banco San Juan / BNA) más el spread operativo, respetando los topes máximos legales admitidos.
5. **Control Estricto de Garantías y Fiadores Solidarios:**
   * Para afiliados calificados con riesgo o que soliciten montos ampliados, se exige fiador solidario matriculado.
   * **Regla Inquebrantable:** Un afiliado no puede ser fiador si posee préstamos propios en mora, si ya actúa como garante en otro crédito con cuotas impagas o si registra deudas de aportes previsionales con la Caja.
6. **Integración con Boletas y Cobranza:** Las cuotas devengadas se integran automáticamente en la cuenta corriente del escribano o se adicionan como concepto discriminado en su boleta mensual de pago.

---

### 2. Modelo de Datos Relacional (PostgreSQL DDL)

```sql
-- Tabla de Líneas de Préstamos Habilitadas por Directorio
CREATE TABLE IF NOT EXISTS prestamos_lineas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo VARCHAR(50) UNIQUE NOT NULL, -- 'LINEA_COMUN', 'RECIEN_MATRICULADOS', 'PASIVOS', 'EXTRAORDINARIO'
    nombre VARCHAR(150) NOT NULL,
    descripcion TEXT,
    sistema_amortizacion VARCHAR(20) NOT NULL DEFAULT 'FRANCES', -- 'FRANCES', 'ALEMAN'
    plazo_minimo_meses INT NOT NULL DEFAULT 6,
    plazo_maximo_meses INT NOT NULL DEFAULT 48,
    monto_minimo NUMERIC(15, 2) NOT NULL DEFAULT 100000.00,
    monto_maximo NUMERIC(15, 2) NOT NULL DEFAULT 10000000.00,
    tasa_nominal_anual NUMERIC(6, 4) NOT NULL, -- Ej: 0.4200 (42% TNA)
    porcentaje_max_afectacion NUMERIC(4, 2) NOT NULL DEFAULT 0.30, -- 30% del ingreso
    requiere_garante BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

-- Tabla de Solicitudes y Operaciones de Préstamos
CREATE TABLE IF NOT EXISTS prestamos_solicitudes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero_operacion VARCHAR(50) UNIQUE NOT NULL, -- Ej: 'PRE-2026-00341'
    escribano_id UUID NOT NULL REFERENCES padron_escribanos(id) ON DELETE RESTRICT,
    linea_id UUID NOT NULL REFERENCES prestamos_lineas(id) ON DELETE RESTRICT,
    
    -- Parámetros Financieros Aprobados
    capital_solicitado NUMERIC(15, 2) NOT NULL,
    cantidad_cuotas INT NOT NULL,
    tasa_nominal_anual_aplicada NUMERIC(6, 4) NOT NULL,
    costo_financiero_total NUMERIC(6, 4),
    sistema_amortizacion VARCHAR(20) NOT NULL,
    
    -- Evaluación Crediticia y Afectación
    ingreso_mensual_acreditado NUMERIC(15, 2) NOT NULL,
    porcentaje_afectacion_calculado NUMERIC(4, 2) NOT NULL,
    dictamen_evaluacion VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE, APROBADA, RECHAZADA, CANCELADA
    
    -- Garante Solidario (Si aplica)
    garante_escribano_id UUID REFERENCES padron_escribanos(id),
    
    -- Estados y Liquidación
    estado VARCHAR(30) NOT NULL DEFAULT 'INICIADA', -- INICIADA, EN_ANALISIS, OTORGADA, EN_CURSO, CANCELADA_TOTAL
    fecha_otorgamiento DATE,
    fecha_primer_vencimiento DATE,
    aprobado_por_user_id UUID REFERENCES security_users(id),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_prestamos_escribano ON prestamos_solicitudes(escribano_id);
CREATE INDEX idx_prestamos_estado ON prestamos_solicitudes(estado);

-- Tabla del Cuadro de Amortización (Plan de Cuotas)
CREATE TABLE IF NOT EXISTS prestamos_cuotas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    solicitud_id UUID NOT NULL REFERENCES prestamos_solicitudes(id) ON DELETE CASCADE,
    numero_cuota INT NOT NULL,
    
    -- Desglose Financiero Exacto
    saldo_capital_inicial NUMERIC(15, 2) NOT NULL,
    amortizacion_capital NUMERIC(15, 2) NOT NULL,
    interes_compensatorio NUMERIC(15, 2) NOT NULL,
    gasto_administrativo_seguro NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    monto_cuota_total NUMERIC(15, 2) NOT NULL,
    saldo_capital_final NUMERIC(15, 2) NOT NULL,
    
    -- Fechas y Cobranza
    fecha_vencimiento DATE NOT NULL,
    fecha_pago TIMESTAMPTZ,
    interes_mora_devengado NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cobrado NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE, PAGADA, VENCIDA
    
    CONSTRAINT uq_solicitud_cuota UNIQUE (solicitud_id, numero_cuota)
);

CREATE INDEX idx_cuotas_vencimiento ON prestamos_cuotas(fecha_vencimiento, estado);
```

---

### 3. Motor Financiero de Amortización (`backend/app/services/prestamos_math.py`)

```python
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from typing import List, Dict, Any

class SimuladorAmortizacionService:
    """Calcula cuadros de marcha de préstamos bajo sistemas Francés y Alemán con precisión Decimal."""

    @classmethod
    def generar_sistema_frances(
        cls,
        capital: Decimal,
        tasa_nominal_anual: Decimal,
        cantidad_cuotas: int,
        fecha_primer_vencimiento: date,
        gasto_seguro_mensual: Decimal = Decimal("0.00")
    ) -> List[Dict[str, Any]]:
        # Tasa efectiva mensual = TNA / 12
        i = (tasa_nominal_anual / Decimal("12")).quantize(Decimal("0.00000001"))
        
        # Fórmula de cuota constante sistema francés: R = C * [i * (1 + i)^n] / [(1 + i)^n - 1]
        factor = (Decimal("1") + i) ** cantidad_cuotas
        cuota_pura = capital * ((i * factor) / (factor - Decimal("1")))
        cuota_pura = cuota_pura.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        saldo_capital = capital
        plan_cuotas = []

        for n in range(1, cantidad_cuotas + 1):
            interes = (saldo_capital * i).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            # En la última cuota se ajusta el redondeo de capital
            if n == cantidad_cuotas:
                amortizacion = saldo_capital
                cuota_total = amortizacion + interes + gasto_seguro_mensual
                saldo_final = Decimal("0.00")
            else:
                amortizacion = cuota_pura - interes
                cuota_total = cuota_pura + gasto_seguro_mensual
                saldo_final = saldo_capital - amortizacion

            # Cálculo de fecha de vencimiento mensual
            anio = fecha_primer_vencimiento.year + (fecha_primer_vencimiento.month + (n - 1) - 1) // 12
            mes = (fecha_primer_vencimiento.month + (n - 1) - 1) % 12 + 1
            dia = min(fecha_primer_vencimiento.day, 28)
            vencimiento_cuota = date(anio, mes, dia)

            plan_cuotas.append({
                "numero_cuota": n,
                "saldo_capital_inicial": str(saldo_capital),
                "amortizacion_capital": str(amortizacion),
                "interes_compensatorio": str(interes),
                "gasto_administrativo_seguro": str(gasto_seguro_mensual),
                "monto_cuota_total": str(cuota_total),
                "saldo_capital_final": str(saldo_final),
                "fecha_vencimiento": vencimiento_cuota.isoformat()
            })

            saldo_capital = saldo_final

        return plan_cuotas
```

---

### 4. Controlador de Préstamos (`backend/app/api/v1/endpoints/prestamos.py`)

```python
import uuid
from decimal import Decimal
from datetime import date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.core.database import get_db_session
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.padron import Escribano
from app.models.prestamos import PrestamoLinea, PrestamoSolicitud, PrestamoCuota
from app.services.prestamos_math import SimuladorAmortizacionService
from pydantic import BaseModel, Field

router = APIRouter(prefix="/prestamos", tags=["Préstamos Previsionales"])

class SimulacionRequest(BaseModel):
    linea_id: uuid.UUID
    capital: Decimal = Field(..., gt=Decimal("0.00"))
    cuotas: int = Field(..., ge=6, le=72)
    ingreso_mensual: Decimal = Field(..., gt=Decimal("0.00"))

@router.post("/simular", response_model=dict)
async def simular_prestamo(
    req: SimulacionRequest,
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(PrestamoLinea).where(PrestamoLinea.id == req.linea_id, PrestamoLinea.is_active == True)
    linea = (await db.execute(stmt)).scalar_one_or_none()

    if not linea:
        raise HTTPException(status_code=404, detail="Línea de préstamo no disponible.")
    if req.capital < linea.monto_minimo or req.capital > linea.monto_maximo:
        raise HTTPException(status_code=400, detail=f"Monto fuera de rango (${linea.monto_minimo} - ${linea.monto_maximo}).")
    if req.cuotas < linea.plazo_minimo_meses or req.cuotas > linea.plazo_maximo_meses:
        raise HTTPException(status_code=400, detail=f"Plazo en cuotas no admitido ({linea.plazo_minimo_meses} - {linea.plazo_maximo_meses}).")

    cuotas_plan = SimuladorAmortizacionService.generar_sistema_frances(
        capital=req.capital,
        tasa_nominal_anual=linea.tasa_nominal_anual,
        cantidad_cuotas=req.cuotas,
        fecha_primer_vencimiento=date.today()
    )

    primera_cuota = Decimal(cuotas_plan[0]["monto_cuota_total"])
    porcentaje_afectacion = (primera_cuota / req.ingreso_mensual).quantize(Decimal("0.0001"))
    es_viable = porcentaje_afectacion <= linea.porcentaje_max_afectacion

    return {
        "linea_nombre": linea.nombre,
        "capital": str(req.capital),
        "cuotas": req.cuotas,
        "tna": str(linea.tasa_nominal_anual),
        "primera_cuota": str(primera_cuota),
        "porcentaje_afectacion": f"{porcentaje_afectacion * 100:.2f}%",
        "afectacion_maxima_permitida": f"{linea.porcentaje_max_afectacion * 100:.2f}%",
        "es_viable": es_viable,
        "plan_cuotas": cuotas_plan
    }
```
