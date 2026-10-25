# Documento de Ingeniería de Software — Módulo 11
## Estrategia de Migración de Datos, Auditoría Previa y Puesta en Marcha
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Requerimientos del Pliego:** Decisión `D-03`, `OPS-01`, `OPS-02`, `OPS-03`, `SEC-06`, Criterios de Aceptación  
**Stack de Referencia:** Python 3.12+ | Alembic | PostgreSQL 16+ | Docker | Pandas / Polars (ETL)

---

### 1. Propósito, Alcance y Principios de la Decisión D-03

El **Módulo 11 (Migración y Puesta en Marcha)** define la metodología de relevamiento, saneamiento, conversión y corte operativo para sustituir la suite observada por la nueva plataforma de la Caja Notarial de San Juan sin comprometer la continuidad del servicio ni la integridad de los saldos históricos.

#### 1.1 Principios Rectores Confirmados
1. **Auditoría Previa de Estructura y Volumen antes de Migrar (`D-03`):**
   * Se prohíbe terminantemente ejecutar cargas masivas o descargas indiscriminadas de datos reales sin antes auditar los motores de base de datos origen, esquemas, diccionarios, codificaciones de caracteres y volumen de adjuntos.
   * La Caja Notarial debe aprobar formalmente qué datos y períodos históricos se trasladan de forma transaccional y cuáles se conservan en repositorios históricos de sólo lectura.
2. **Aislamiento y Confidencialidad (`SEC-06`):**
   * El desarrollo y las pruebas previas se ejecutan exclusivamente sobre fixtures sintéticos o datos anonimizados.
   * La extracción de datos de producción se realiza con autorización expresa, mediante canales cifrados y bajo estricta custodia.
3. **Conciliación Actuarial y Contable al Céntimo:**
   * La migración de boletas, pagos y saldos de aportes debe conciliar al 100% entre el sistema anterior y la nueva base de datos PostgreSQL. Cualquier discrepancia debe documentarse con causa justificada, quedando prohibido "forzar" o balancear saldos con asientos ficticios.
4. **Plan de Reversa Inmediata (Rollback Plan):**
   * La ventana de corte (*Cutover*) debe contar con un procedimiento de reversa totalmente ensayado y documentado para restituir el sistema anterior en caso de falla crítica imprevista durante las primeras 48 horas.

---

### 2. Cronograma de Fases de Migración y Puesta en Marcha

```text
[FASE 1: Auditoría Técnica y Relevamiento de Motores]
  - Análisis de esquemas DDL legados, volúmenes y calidad de datos
  - Inventario de comprobantes y documentos almacenados
  - Determinación de reglas de limpieza y homologación de estados
                              |
                              v
[FASE 2: Mapeo Conceptual y Desarrollo de Scripts ETL]
  - Desarrollo de scripts Python de extracción, transformación y carga
  - Tratamiento de CUITs duplicados, matrículas y normalización de fechas a UTC
  - Conversión de montos de float/texto a Numeric(15,2) exacto
                              |
                              v
[FASE 3: Ensayos de Migración en Aislamiento (Dry-Runs)]
  - Ejecución de 3 simulacros completos de migración sobre réplicas de prueba
  - Cotejo y conciliación automática de saldos, boletas y padrón
  - Validación y firma de conformidad por parte de Tesorería y Caja
                              |
                              v
[FASE 4: Ventana de Corte Definitiva (Cutover Weekend)]
  - Congelamiento operativo del sistema legado (Viernes 18:00 hs)
  - Extracción final diferencial y ejecución del pipeline ETL definitivo
  - Verificación de checksums y smoke tests de la nueva suite
                              |
                              v
[FASE 5: Puesta en Marcha (Go-Live) y Soporte Hiperasistido]
  - Apertura del portal de escribanos y panel administrativo (Lunes 08:00 hs)
  - Monitoreo en tiempo real de logs y conciliaciones bancarias
  - Plan de contingencia y mesa de ayuda dedicada
```

---

### 3. Matriz de Homologación de Esquemas (Legado vs Nueva Suite)

| Entidad Legada | Tabla Origen (Observada) | Entidad Destino PostgreSQL | Transformación y Reglas de Calidad |
| :--- | :--- | :--- | :--- |
| **Afiliados / Notarios** | `tbl_escribanos` / planillas | `padron_personas` + `padron_escribanos` | Separación de persona física y matrícula. Validación de CUIT por Módulo 11. Asignación de UUID v4. |
| **Registros Notariales** | `tbl_registros` | `padron_registros_notariales` + `padron_adscripciones` | Determinación unívoca del escribano titular y los adscriptos vigentes. |
| **Declaraciones Juradas** | `tbl_ddjj` | `ddjj_declaraciones` + `ddjj_renglones_escrituras` | Conversión de períodos a formato ISO `YYYY-MM`. Homologación de estados a catálogo oficial. |
| **Boletas y Comprobantes** | `tbl_boletas` | `boletas_pago` + `pagos_comprobantes` | Desacoplamiento de "comprobante adjunto" de "pago confirmado" (`DDJJ-05`). Recálculo de checksums SHA-256. |
| **Balances Oficiales** | Enlaces y archivos locales | `cms_documentos_oficiales` | Validación obligatoria de integridad de archivo con `pypdf` (`WEB-02`). |

---

### 4. Script Maestro de Migración ETL (`scripts/migracion_etl.py`)

```python
import os
import sys
import uuid
import hashlib
from decimal import Decimal
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import execute_batch

def ejecutar_migracion_padron(db_cursor_origen, db_cursor_destino, operador_id: str):
    """
    Extrae los escribanos del sistema legado, normaliza CUITs y los inserta
    en las nuevas tablas relacionales padron_personas y padron_escribanos.
    """
    print("[ETL] Iniciando extracción y normalización del padrón de escribanos...")
    
    # 1. Consulta al sistema legado
    db_cursor_origen.execute("""
        SELECT cuit, matricula, apellido, nombre, dni, email, fecha_matricula, estado
        FROM leg_escribanos
    """)
    filas = db_cursor_origen.fetchall()
    
    personas_a_insertar = []
    escribanos_a_insertar = []
    
    for fila in filas:
        cuit_raw, matricula, apellido, nombre, dni, email, fecha_mat, estado_raw = fila
        
        # Limpieza de CUIT (eliminar guiones y espacios)
        cuit_limpio = "".join(filter(str.isdigit, str(cuit_raw or "")))
        if len(cuit_limpio) != 11:
            print(f"[ALERTA CALIDAD] CUIT inválido ({cuit_raw}) para matrícula {matricula}. Registro observado.")
            continue
            
        persona_id = str(uuid.uuid4())
        escribano_id = str(uuid.uuid4())
        
        personas_a_insertar.append((
            persona_id, cuit_limpio, dni or cuit_limpio[2:10], 'DNI',
            apellido.strip().upper(), nombre.strip().title(), email or None, operador_id
        ))
        
        # Homologación de estados
        estado_normalizado = "ACTIVO"
        if estado_raw and str(estado_raw).upper() in ["BAJA", "SUSPENDIDO", "INACTIVO"]:
            estado_normalizado = "SUSPENDIDO"
            
        escribanos_a_insertar.append((
            escribano_id, persona_id, matricula, fecha_mat or "2000-01-01",
            estado_normalizado, operador_id
        ))

    # 2. Inserción transaccional por lotes en destino
    insert_persona_query = """
        INSERT INTO padron_personas (
            id, cuit, numero_documento, tipo_documento, apellido, nombre, email_personal, created_by_user_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cuit) DO NOTHING;
    """
    execute_batch(db_cursor_destino, insert_persona_query, personas_a_insertar, page_size=500)
    
    insert_escribano_query = """
        INSERT INTO padron_escribanos (
            id, persona_id, matricula_numero, fecha_matriculacion, estado_matricula, created_by_user_id
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (matricula_numero) DO NOTHING;
    """
    execute_batch(db_cursor_destino, insert_escribano_query, escribanos_a_insertar, page_size=500)
    
    print(f"[ETL] Padrón migrado con éxito: {len(personas_a_insertar)} registros procesados.")
```

---

### 5. Plan de Reversa y Contingencia (Rollback Protocol)

Si durante las 48 horas posteriores al corte se presenta una falla insalvable:
1. **Punto de Restauración del Sistema Legado:** Se preservan intactas las bases de datos del sistema anterior en modo de sólo lectura, garantizando su reapertura en menos de 30 minutos.
2. **Reversión de DNS:** Reconfiguración de registros DNS en Nginx y Cloudflare para apuntar el tráfico nuevamente a la infraestructura anterior.
3. **Conciliación de Operaciones del Fin de Semana:** Cualquier comprobante o boleta emitida durante el fin de semana de corte se descarga en archivo CSV auditado para su inserción manual en el sistema recuperado.
4. **Comité de Contingencia:** El Gerente de Caja, el Responsable de Sistemas y el Auditor General suscriben el acta de corte o de reversa formal.
