# Suite Notarial — Caja Notarial de San Juan
## Playbook de Construcción por Fases (instrucciones para el Agente)

> **Dónde va este archivo:** raíz del repo (`/Users/Jorge/Documents/GitHub/Suite_notarial/`).
> Guardalo como `AGENTS.md` **y** `PLAN_CONSTRUCCION.md` (así Claude Code lo auto-lee).
> **Repo:** https://github.com/jaillanez/suite-notarial.git

---

## 0. META-INSTRUCCIONES PARA EL AGENTE (leer antes de todo)

1. **Rol:** Arquitecto Principal Full-Stack, grado producción. Seguridad, integridad contable-previsional y UX de escribanos por encima de la velocidad.
2. **Diseño frontend:** antes de escribir CUALQUIER componente o página, invocá la skill **`impeccable`** (ya instalada). Todo el UI sale de ahí. No improvises estilos.
3. **Entorno:** **SIN Docker.** PostgreSQL local ya instalado. Todo corre nativo (venv + Vite + binarios locales). Mailpit como binario local (`brew install mailpit`), no contenedor.
4. **Ritmo de trabajo:**
   - Una rama por fase: `feat/fase-0-bootstrap`, `feat/fase-1-iam`, etc.
   - Un commit atómico por tarea, mensaje claro (`feat(iam): endpoint login con cookie HttpOnly`).
   - **No se cierra una fase** hasta cumplir su *Definition of Done (DoD)*: tests verdes + linters + migración aplicada + README actualizado.
   - PR al final de cada fase. Pará y reportá antes de empezar la siguiente.
5. **No avanzar con supuestos:** si un parámetro de negocio real (alícuotas, topes, formato de boleta) no está definido, dejá un `TODO(negocio)` visible y seguí con valores de ejemplo claramente marcados. Nunca inventes números como si fueran oficiales.
6. **Código completo:** nada de `# implementar acá` ni `// resto del código`. Todo tipado y funcional.

---

## 1. REGLAS INNEGOCIABLES (resumen operativo — aplican en TODAS las fases)

| # | Regla | Cómo se verifica |
|---|-------|------------------|
| **FIN** | Cero flotantes para dinero/tasas. Python `Decimal` + `ROUND_HALF_UP`. SQL `Numeric(15,2)` montos, `Numeric(18,4)`/`Numeric(6,4)` tasas. | Test que falla si aparece `float` en lógica monetaria. Lint custom. |
| **SEC-04** | Enlaces de mail SIEMPRE desde `PUBLIC_WEB_URL` (env tipada). Prohibido `localhost`/IP privada en plantillas. | Test que escanea plantillas. |
| **SEC-01** | Autorización en backend con `Depends(require_permissions(...))`. Ocultar en React ≠ seguridad. | Test de endpoint sin permiso → 403. |
| **AUD** | Toda acción sensible → fila inmutable en `audit_security_logs` (actor, UTC, IP, valor previo/nuevo). | Test que verifica el log tras la acción. |
| **INM** | Prohibido `DELETE` físico en afiliados/matrículas/parámetros/liquidaciones. Baja lógica (`is_active`, `SUSPENDIDO`, `CESANTE`). | Revisión de modelos + tests. |
| **SNAP** | Cada boleta guarda el `id` de la vigencia paramétrica con que se calculó. Cambiar parámetros NO altera boletas viejas. | Test de inmutabilidad retroactiva. |
| **PAGO** | Adjuntar comprobante ≠ pago confirmado. Queda `PENDIENTE_REVISION` hasta validación de Tesorería. | Test de máquina de estados. |
| **MIME** | Uploads validados por *magic bytes* (`python-magic`): solo PDF/PNG/JPG, máx 10 MB, nombre UUID, fuera del webroot ejecutable. | Test con archivo falsificado. |
| **HIC** | IA solo asistencial. Ningún modelo sella actos, da fe pública ni mueve saldos. Siempre ratifica un humano. | Revisión de endpoints IA. |
| **REP** | Grillas con paginación **en servidor** + cabeceras fijas. Export XLSX/CSV sale de la MISMA query y filtros. Paridad exacta de totales. | Test que compara totales pantalla vs export. |
| **API** | Errores en RFC 7807 (Problem Details) con HTTP semántico (400/401/403/404/422/500). | Tests de contrato. |

---

## 2. ENTORNO BASE (macOS, sin Docker)

**Versiones objetivo:** Python 3.12+, Node 20 LTS+, PostgreSQL 16+.

**Servicios locales que reemplazan a docker-compose:**
- PostgreSQL local (ya instalado) → base `suite_notarial`.
- Mailpit local → SMTP `localhost:1025`, UI `http://localhost:8025`.
- Backend → `uvicorn` en `localhost:8000`.
- Frontend → Vite dev en `localhost:5173`.
- Orquestación → `Makefile` (sustituye a Compose).

Nginx/SSL/cabeceras seguras quedan documentadas para producción, pero **no se usan en desarrollo**.

---

## 3. FASE 0 — BOOTSTRAP Y CIMIENTOS

**Objetivo:** monorepo funcional, backend que levanta y se conecta a la BD local, frontend que renderiza, migraciones vivas, tooling de calidad, y healthcheck end-to-end. **Sin lógica de negocio todavía.**

### Paso 0.1 — Repo y estructura
```bash
cd /Users/Jorge/Documents/GitHub/Suite_notarial
git init 2>/dev/null; git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/jaillanez/suite-notarial.git
git checkout -b feat/fase-0-bootstrap
```
Crear árbol:
```
suite-notarial/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── core/        # config.py, db.py, security.py, logging.py, errors.py
│   │   ├── modules/     # una carpeta por módulo (iam/, padron/, ...)
│   │   ├── common/      # deps.py, pagination.py, audit.py, money.py
│   │   └── db/          # base.py (DeclarativeBase), session
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
├── frontend/            # scaffold Vite React-TS
├── scripts/
│   ├── bootstrap_db.sh
│   └── dev.sh
├── docs/
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
└── README.md
```

### Paso 0.2 — Base de datos local
`scripts/bootstrap_db.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
DB=suite_notarial
ROLE=suite_app
PASS=suite_app_dev   # solo desarrollo; prod va por env/secreto
psql -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'" | grep -q 1 || \
  psql -d postgres -c "CREATE ROLE $ROLE LOGIN PASSWORD '$PASS';"
psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 || \
  psql -d postgres -c "CREATE DATABASE $DB OWNER $ROLE;"
psql -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"  # habilita gen_random_uuid()
echo "OK: base $DB lista."
```
> `pgcrypto` es obligatorio: los UUID v4 se generan con `gen_random_uuid()` del lado de PostgreSQL.

### Paso 0.3 — Backend (pyproject + deps)
`backend/pyproject.toml` (deps principales):
- Runtime: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`.
- Seguridad: `pyjwt`, `argon2-cffi` (hash de contraseñas), `pyotp` (2FA), `python-magic`.
- Documentos: `weasyprint` (HTML→PDF para boletas) o `reportlab`; `qrcode[pil]`, `python-barcode`; `openpyxl` (XLSX).
- Email: `aiosmtplib` + `jinja2` (plantillas).
- Dev/test: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`, `types-*`.

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"   # definir extras en pyproject
```
> `python-magic` en Mac requiere `brew install libmagic`. `weasyprint` requiere `brew install pango gdk-pixbuf libffi`. Documentar en README.

### Paso 0.4 — Config tipada (`app/core/config.py`)
`Settings(BaseSettings)` con, como mínimo:
`ENVIRONMENT`, `DATABASE_URL` (`postgresql+asyncpg://suite_app:...@localhost:5432/suite_notarial`), `PUBLIC_WEB_URL`, `JWT_SECRET`, `JWT_ACCESS_TTL_MIN`, `JWT_REFRESH_TTL_DAYS`, `COOKIE_SECURE`, `COOKIE_DOMAIN`, `SMTP_HOST=localhost`, `SMTP_PORT=1025`, `MAIL_FROM`, `PASSWORD_RESET_TTL_MIN=30`, `UPLOAD_DIR`, `MAX_UPLOAD_MB=10`.
`.env.example` con todas las claves, **sin secretos reales**. `.env` va en `.gitignore`.

### Paso 0.5 — DB async + Base declarativa
- `app/db/base.py`: `DeclarativeBase` + mixin `TimestampMixin` (`created_at`/`updated_at` `TIMESTAMPTZ` en UTC) y `UUIDMixin` (`id` UUID PK con `server_default=gen_random_uuid()`).
- `app/core/db.py`: `async_engine` + `async_sessionmaker` + dependencia `get_session()`.
- `app/common/money.py`: helpers `to_money(x) -> Decimal` (quantize a 2 dec, `ROUND_HALF_UP`) y `to_rate(x) -> Decimal` (4 dec). Prohibido manejar dinero fuera de estos helpers.

### Paso 0.6 — Alembic
```bash
cd backend && alembic init -t async alembic
```
Configurar `env.py` para leer `DATABASE_URL` de settings y el `metadata` de la Base. Primera migración vacía (base limpia):
```bash
alembic revision -m "fase0_base" --autogenerate
alembic upgrade head
```

### Paso 0.7 — App + healthcheck + errores RFC 7807
- `app/main.py`: crea `FastAPI`, monta router de health, registra *exception handlers* que devuelven Problem Details (`application/problem+json`).
- `GET /api/health` → `{status, db: "up"/"down", time_utc}` (hace un `SELECT 1` real).
- `app/core/logging.py`: logging estructurado (JSON) básico.

### Paso 0.8 — Frontend
```bash
cd frontend && npm create vite@latest . -- --template react-ts
npm i axios @tanstack/react-query @tanstack/react-table tailwindcss
```
- Tailwind configurado. TS en **modo estricto** (`strict: true`).
- Cliente Axios con `withCredentials: true` (cookies HttpOnly).
- Página mínima que llama `/api/health` y muestra el estado. **El estilo lo define la skill `impeccable`.**

### Paso 0.9 — Orquestación local (`Makefile`)
Targets: `db` (bootstrap_db.sh), `mailpit` (lanza mailpit), `backend` (uvicorn reload), `frontend` (vite), `dev` (todo junto), `migrate`, `revision m=...`, `test`, `lint`, `fmt`.

### Paso 0.10 — Calidad (`.pre-commit-config.yaml`)
- Python: `ruff` (lint+format), `mypy`.
- Frontend: `eslint`, `prettier`, `tsc --noEmit`.
- Hook que bloquea `print(` perdidos y, en módulos monetarios, el token `float`.

### Paso 0.11 — README
Instrucciones de arranque en limpio: brew deps, `make db`, `make migrate`, `make dev`. Variables de entorno. Puertos.

### ✅ DoD Fase 0
- [ ] `make db && make migrate` deja la BD migrada sin errores.
- [ ] `make dev` levanta backend (8000), frontend (5173) y mailpit (8025).
- [ ] `GET /api/health` responde `db: up`.
- [ ] Frontend muestra el estado del health en pantalla.
- [ ] `make lint` y `make test` verdes (test de `/health` + test de `money.py` con `ROUND_HALF_UP`).
- [ ] Pre-commit instalado y pasando. PR de `feat/fase-0-bootstrap` abierto.

---

## 4. FASES 1 A 10 (spec por fase)

> Formato de cada fase: **Objetivo → Entregables → Tareas clave → Reglas aplicadas → Tests → DoD.** El agente desarrolla una fase completa, abre PR y se detiene.

### FASE 1 — IAM & RBAC
- **Objetivo:** identidad, sesión y permisos de grado producción.
- **Entregables:** modelo `users`, `roles`, `permissions`, `role_permissions`; login JWT en **cookie HttpOnly + Secure + SameSite**; refresh; logout; 2FA TOTP (`pyotp`, enrolar/verificar/recovery codes); recuperación de contraseña por mail; `audit_security_logs`.
- **Tareas:** `require_permissions(...)` como dependencia; hash con Argon2; token reset de **un solo uso**, hash **SHA-256** en BD, TTL 30 min; endpoint de reset **anti-enumeración** (siempre mismo mensaje genérico); enlaces desde `PUBLIC_WEB_URL`; plantillas Jinja enviadas vía Mailpit.
- **Reglas:** SEC-01, SEC-04, AUD.
- **Tests:** login OK/KO; endpoint protegido sin permiso → 403; token reset caducado/reusado → rechazo; plantilla sin `localhost`; 2FA verify.
- **DoD:** flujo completo login→2FA→acción protegida→reset de clave probado punta a punta con Mailpit.

### FASE 2 — Padrón de Escribanos y Registros
- **Objetivo:** personas físicas, matrículas, titulares/adscriptos, circunscripciones.
- **Entregables:** modelos con baja lógica; validación **CUIT Módulo 11**; estados de matrícula (`ACTIVO`/`SUSPENDIDO`/`CESANTE`); relación titular↔adscripto; ABM con auditoría.
- **Reglas:** INM (sin DELETE), AUD.
- **Tests:** CUIT válido/ inválido (Módulo 11, casos borde incl. dígito 10→"23/24"), baja lógica no borra, cambio de estado auditado.
- **DoD:** ABM completo + grilla de escribanos (ya con paginación servidor, anticipando REP).

### FASE 3 — Motor Paramétrico de Aportes
- **Objetivo:** catálogo de parámetros con vigencias temporales e inmutabilidad histórica.
- **Entregables:** tabla de parámetros versionados (`vigencia_desde`/`vigencia_hasta`, nunca se sobreescribe: nueva vigencia = nueva fila); tipos (porcentual sobre escritura, fijo mensual, tasa de mora, regla de redondeo); resolución "parámetro vigente a fecha X".
- **Reglas:** FIN (`Numeric` correcto), INM, AUD.
- **Tests:** solapamiento de vigencias rechazado; resolución por fecha correcta; cambio crea versión nueva sin tocar la anterior.
- **DoD:** servicio `get_vigencia(tipo, fecha)` probado; ABM con auditoría.

### FASE 4 — DDJJ y Boletas
- **Objetivo:** carga mensual de escrituras y emisión de boletas oficiales.
- **Entregables:** DDJJ por escribano/período; **cálculo 100% en backend** (nunca confiar en montos del cliente); boleta con **snapshot del `id` de vigencia** usado; PDF oficial con **QR + código de barras**; numeración de boleta.
- **Reglas:** FIN, SNAP, SEC-01, AUD.
- **Tests:** recálculo determinístico; boleta vieja no cambia al modificar parámetros (SNAP); QR/barras generados; mora aplicada según parámetro vigente.
- **DoD:** generar boleta real desde una DDJJ, PDF descargable y verificable.

### FASE 5 — Pagos y Conciliación
- **Objetivo:** comprobantes y mesa de conciliación de Tesorería.
- **Entregables:** upload con validación **magic bytes** (`python-magic`, PDF/PNG/JPG, ≤10MB, nombre UUID, fuera de webroot); estado `PENDIENTE_REVISION`→`CONCILIADO`/`RECHAZADO`; mesa de conciliación manual (y gancho para conciliación bancaria futura).
- **Reglas:** MIME, PAGO (adjuntar ≠ pagado), AUD.
- **Tests:** archivo con extensión falsa → rechazo; estado no salta a conciliado sin acción de Tesorería; auditoría de conciliación.
- **DoD:** cargar comprobante, revisarlo en la mesa, conciliar, y ver la boleta pasar a pagada.

### FASE 6 — Reportes y Auditoría
- **Objetivo:** grillas y exportación con paridad pantalla↔Excel.
- **Entregables:** paginación **en servidor** + **sticky headers** (TanStack Table v8); export XLSX/CSV desde **la misma query/filtros**; visor de `audit_security_logs`.
- **Reglas:** REP.
- **Tests:** totales pantalla == totales export; sin scroll horizontal infinito; permisos sobre reportes sensibles.
- **DoD:** al menos 3 reportes clave (escribanos, boletas, pagos) exportables con totales idénticos.

### FASE 7 — CMS y Sitio Institucional
- **Objetivo:** publicación institucional con integridad verificable.
- **Entregables:** autoridades, novedades, estados contables (PDF); **verificación binaria de integridad** de PDFs (hash almacenado y chequeado al servir/descargar).
- **Reglas:** MIME, AUD.
- **Tests:** PDF alterado → detectado por hash; publicación auditada.
- **DoD:** sección pública renderiza contenidos y valida integridad.

### FASE 8 — Servicios Previsionales y Préstamos
- **Objetivo:** líneas de crédito y control previsional.
- **Entregables:** préstamos **sistema Francés y Alemán** (cuotas con `Decimal`); **topes de afectación** de ingresos netos (25%–30%); intereses sobre saldos; control de fiadores.
- **Reglas:** FIN (crítico en amortización), INM, AUD.
- **Tests (pytest obligatorios):** cuadro de amortización Francés y Alemán contra valores de referencia; tope de afectación bloquea otorgamiento; redondeo final cuadra el saldo a cero.
- **DoD:** simular y otorgar un préstamo con cuadro completo y validaciones de tope/fiadores.

### FASE 9 — IA Asistencial y Fe Pública
- **Objetivo:** OCR/NLP asistencial bajo **Human in Command**.
- **Entregables:** OCR de DNI y extracción de minutas como **sugerencia**; toda salida entra en estado `SUGERIDO_POR_IA` y requiere **ratificación explícita** del escribano/funcionario; nunca escribe saldos ni sella actos.
- **Reglas:** HIC, AUD (registrar sugerencia IA + quién ratifica).
- **Tests:** ningún endpoint IA muta saldos/estados definitivos; la ratificación humana es obligatoria y queda auditada.
- **DoD:** flujo "IA sugiere → humano revisa/edita → humano confirma" funcionando y registrado.

### FASE 10 — Migración y Puesta en Marcha
- **Objetivo:** pasar del sistema legado a producción con red de seguridad.
- **Entregables:** ETL (extracción legado → staging → validación → carga); **validación actuarial 100%** (los saldos/aportes migrados cuadran con el origen); **protocolo de rollback < 30 min** documentado y ensayado; checklist de corte.
- **Reglas:** INM, FIN, AUD.
- **Tests:** reconciliación origen↔destino al centavo; ensayo de rollback cronometrado.
- **DoD:** corrida de migración en datos de prueba con reporte de cuadratura y rollback probado.

---

## 5. ORDEN DE DEPENDENCIAS (no saltear)
`0 → 1 → 2 → 3 → 4 → 5 → 6` es la columna vertebral. `7` puede ir en paralelo tras `1`. `8` depende de `2` y `3`. `9` depende de `2` y `4`. `10` es la última, depende de todo.

---

## 6. ARRANQUE INMEDIATO
Empezá **ahora** por **Fase 0, Paso 0.1**. No pidas confirmación para tareas de scaffolding reversibles. Al terminar la Fase 0, abrí el PR y detenete para revisión antes de la Fase 1.
