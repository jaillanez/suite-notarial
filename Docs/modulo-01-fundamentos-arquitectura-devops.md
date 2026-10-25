# Documento de Ingeniería de Software — Módulo 1 (v2.1)
## Fundamentos de Arquitectura, Entorno y DevOps (Core & Setup)
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 2.1.0 | **Estado:** Especificación Técnica — alineada con la Fase 0 construida  
**Requerimientos del Pliego:** `SEC-01`, `SEC-03`, `SEC-04`, `OPS-01`, `OPS-02`, `OPS-03`, `D-01`, `D-02`, `D-03`  
**Stack de Referencia:** Python 3.12+ | FastAPI | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Alembic | React 19 + TypeScript | Vite | Tailwind CSS v4 | Mailpit | GitHub Actions

> **Cambios respecto de la v2.0:** el proyecto se desarrolla **sin Docker**. PostgreSQL y Mailpit corren
> como servicios nativos de la máquina y la orquestación local es un `Makefile`. La estructura de carpetas,
> los nombres de variables y los endpoints se ajustaron a lo construido en la Fase 0. El playbook de fases
> (`AGENTS.md`) prevalece ante cualquier diferencia con este documento.

---

### 1. Propósito, Alcance y Mitigación de Defectos Previos

El **Módulo 1** establece la infraestructura base, el andamiaje del código fuente, las políticas de persistencia financiera y los estándares de seguridad operativa que regirán transversalmente sobre todos los módulos de la suite.

Este diseño fundacional erradica las deficiencias críticas detectadas en auditorías sobre sistemas anteriores:
1. **Emisión de enlaces rotos o locales (`SEC-04`):** se elimina el fallo en el cual los correos de recuperación de contraseña emitían enlaces a `localhost:8080`. La configuración tipada con `pydantic-settings` obliga a que todo enlace generado salga de `PUBLIC_WEB_URL`, y fuera de desarrollo/test esa URL no puede apuntar a un host privado.
2. **Imprecisión en cálculos monetarios:** se prohíbe de forma absoluta el uso de coma flotante (`float`, `real`, `double precision`) en Python y en las tablas, imponiendo `Numeric` en PostgreSQL y `Decimal` con `ROUND_HALF_UP` en Python.
3. **Inconsistencia entre entornos (`OPS-03`):** se resuelve con versiones mínimas declaradas (Python 3.12+, Node 20+, PostgreSQL 16+), dependencias fijadas (`package-lock.json`, `pyproject.toml`), configuración 100% por variables de entorno tipadas y un pipeline de CI que levanta la suite desde cero en cada push contra un PostgreSQL limpio. No se usan contenedores en desarrollo.
4. **Vulnerabilidades en control de acceso (`SEC-01`):** toda verificación de permisos y roles se ejecuta en el backend FastAPI mediante dependencias declarativas (`Depends(require_permissions(...))`, Fase 1). Ocultar un botón en React nunca es una medida de seguridad.
5. **Gobernanza sobre desarrollo con agentes de IA:** el archivo `AGENTS.md` impide que agentes autónomos deduzcan o alteren reglas financieras, expongan secretos o interactúen con bases productivas.

---

### 2. Estructura del Repositorio (Monorepo)

```text
Suite_notarial/
├── .github/
│   └── workflows/
│       └── ci.yml                    # Backend: migraciones reversibles, ruff, mypy, pytest · Frontend: ESLint, Prettier, tsc, Vitest, build
├── backend/
│   ├── alembic/                      # Control de versiones del esquema relacional
│   │   ├── versions/                 # Migraciones individuales (upgrade / downgrade)
│   │   ├── env.py                    # Conexión async; lee DATABASE_URL de Settings
│   │   └── script.py.mako
│   ├── app/
│   │   ├── core/                     # Servicios transversales
│   │   │   ├── config.py             # Settings tipados (pydantic-settings)
│   │   │   ├── db.py                 # Engine async, sessionmaker y get_session()
│   │   │   ├── errors.py             # Errores RFC 7807 (application/problem+json)
│   │   │   ├── middleware.py         # X-Correlation-ID y cabeceras de seguridad
│   │   │   ├── logging.py            # Logging estructurado JSON
│   │   │   └── security.py           # Tokens aleatorios, SHA-256, comparación en tiempo constante
│   │   ├── db/
│   │   │   ├── base.py               # DeclarativeBase, naming convention, UUIDMixin, TimestampMixin
│   │   │   ├── models.py             # Registro central de modelos para Alembic
│   │   │   └── session.py
│   │   ├── common/                   # deps.py (SessionDep, SettingsDep), money.py (Decimal)
│   │   ├── modules/                  # Un paquete por módulo de negocio
│   │   │   └── health/router.py      # GET /api/health
│   │   └── main.py                   # Factoría create_app() y ciclo de vida
│   ├── tests/                        # pytest + httpx (ASGI) contra la base suite_notarial_test
│   ├── alembic.ini
│   ├── pyproject.toml                # Dependencias, extras [dev], ruff, mypy strict, pytest
│   └── .env.example                  # Catálogo de variables, sin secretos reales
├── frontend/                         # Vite + React + TypeScript estricto + Tailwind v4
│   ├── src/
│   │   ├── components/               # Componentes UI reutilizables
│   │   ├── features/                 # Una carpeta por funcionalidad (api, hooks, páginas, tests)
│   │   ├── lib/                      # Cliente Axios, utilidades de fecha
│   │   └── main.tsx
│   ├── package.json / package-lock.json
│   └── vite.config.ts                # Proxy /api → backend (mismo origen para cookies HttpOnly)
├── scripts/
│   ├── bootstrap_db.sh               # Crea rol, bases y extensión pgcrypto (idempotente)
│   ├── dev.sh                        # Levanta Mailpit + backend + frontend
│   └── check_forbidden_tokens.py     # Guarda de pre-commit/CI: print( y float en dinero
├── Docs/                             # Especificación funcional por módulo
├── .pre-commit-config.yaml
├── AGENTS.md                         # Playbook de fases y protocolo obligatorio para agentes
├── PRODUCT.md / DESIGN.md            # Producto y sistema de diseño
├── Makefile                          # Orquestación local (reemplaza a docker-compose)
└── README.md
```

---

### 3. Entorno Local Nativo y DevOps

#### 3.1 Servicios locales (sin contenedores)

| Servicio | Cómo corre | Dirección |
|----------|------------|-----------|
| PostgreSQL 16+ | Instalación nativa (Homebrew en macOS) | `localhost:5432`, bases `suite_notarial` y `suite_notarial_test` |
| Mailpit | Binario nativo (`brew install mailpit`) | SMTP `localhost:1025`, UI `http://localhost:8025` |
| Backend | `uvicorn` dentro del venv `backend/.venv` | `http://localhost:8000` |
| Frontend | Vite dev server | `http://localhost:5173` |

Los puertos de backend y frontend son configurables (`make dev API_PORT=8010 WEB_PORT=5183`) para convivir con otros proyectos locales.

#### 3.2 Orquestación (`Makefile`)

| Comando | Acción |
|---------|--------|
| `make install` | venv + dependencias del backend, `npm ci`, hooks de pre-commit; crea `backend/.env` desde `.env.example` |
| `make db` | Ejecuta `scripts/bootstrap_db.sh` |
| `make migrate` / `make revision m="..."` | `alembic upgrade head` / autogenerate |
| `make dev` | Mailpit + backend con recarga + frontend |
| `make test` / `make lint` / `make fmt` | Tests, linters y formateo de backend y frontend |

#### 3.3 Inicialización de la base de datos (`scripts/bootstrap_db.sh`)

Idempotente: crea el rol `suite_app`, las bases `suite_notarial` y `suite_notarial_test` y la extensión `pgcrypto` (provee `gen_random_uuid()` para las PK UUID v4). La migración base `fase0_base` vuelve a garantizar `pgcrypto`, de modo que una base nueva en cualquier entorno queda correcta solo con `alembic upgrade head`. La zona horaria de cada conexión se fija en UTC desde el engine (`server_settings={"timezone": "UTC"}`). No se usa `uuid-ossp`.

#### 3.4 Integración continua (`.github/workflows/ci.yml`)

En cada push y pull request:
- **Backend:** PostgreSQL 16 como servicio del runner de GitHub Actions; `make db`; migraciones `upgrade head → downgrade base → upgrade head` y `alembic check` (sin cambios pendientes de modelo); `ruff`, `mypy --strict`, guarda de `print(`/`float`; `pytest`.
- **Frontend:** `npm ci`; ESLint, Prettier, `tsc`; Vitest; `vite build`.

#### 3.5 Producción

El despliegue productivo (proxy inverso con TLS, cabeceras perimetrales, gestión de secretos y servicio de procesos) se especifica en el Módulo 11 (`modulo-11-migracion-datos-puesta-en-marcha.md`). Este documento no prescribe contenedores para producción.

---

### 4. Capa de Persistencia y Estándares Financieros

#### 4.1 Principios obligatorios de persistencia
- **Precisión decimal absoluta:** montos `Numeric(15, 2)`; alícuotas y tasas `Numeric(6, 4)` o `Numeric(18, 4)`. En Python todo monto pasa por `app/common/money.py` (`to_money`, `to_rate`), que rechaza `float`.
- **Huso horario UTC:** toda fecha y hora se registra como `TIMESTAMPTZ`; la interfaz convierte a `America/Argentina/San_Juan`.
- **Preservación histórica sin borrado físico (`DIR-04`):** ninguna tabla de dominio admite `DELETE` físico; bajas lógicas con `is_active` o estados específicos (`SUSPENDIDO`, `CESANTE`, etc.).

#### 4.2 Motor asíncrono (`backend/app/core/db.py`)

```python
@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.DATABASE_URL),
        pool_pre_ping=True,
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
```

La sesión no hace `commit` implícito: cada servicio confirma explícitamente su unidad de trabajo, de modo que una auditoría y la operación auditada se confirman en la misma transacción.

#### 4.3 Base declarativa y mixins (`backend/app/db/base.py`)

- `Base(DeclarativeBase)` con convención de nombres estable para constraints (Alembic genera nombres deterministas).
- `UUIDMixin`: `id` UUID con `server_default=gen_random_uuid()`.
- `TimestampMixin`: `created_at` / `updated_at` `TIMESTAMPTZ` con `server_default=now()`.
- **Trazabilidad de autoría (`SEC-03`):** `created_by_user_id` y la tabla inmutable `audit_security_logs` (actor, UTC, IP, valor previo y nuevo) se incorporan en la Fase 1, junto con la tabla de usuarios a la que referencian.
- **Baja lógica:** `is_active` se declara en cada modelo de dominio que la requiera (Fase 2 en adelante), no en un mixin genérico, porque algunos dominios usan estados propios.

---

### 5. Configuración del Núcleo FastAPI

#### 5.1 Configuración tipada (`backend/app/core/config.py`)

El servicio no arranca si falta una variable obligatoria o si es inválida.

| Variable | Tipo / regla |
|----------|--------------|
| `ENVIRONMENT` | `development` · `test` · `staging` · `production` |
| `DATABASE_URL` | `PostgresDsn`, obligatoria |
| `PUBLIC_WEB_URL` | `HttpUrl`, obligatoria; en `staging`/`production` no puede ser host privado (`SEC-04`) |
| `CORS_ORIGINS` | Lista de orígenes |
| `JWT_SECRET` | Secreto, obligatorio, mínimo 32 caracteres |
| `JWT_ACCESS_TTL_MIN` / `JWT_REFRESH_TTL_DAYS` | Enteros positivos (15 / 7) |
| `COOKIE_SECURE` / `COOKIE_DOMAIN` | Atributos de la cookie de sesión |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | Correo saliente (Mailpit en desarrollo) |
| `PASSWORD_RESET_TTL_MIN` | 30 |
| `UPLOAD_DIR` / `MAX_UPLOAD_MB` | Comprobantes fuera del webroot; 10 MB |
| `LOG_LEVEL` | Nivel de logging |

#### 5.2 Factoría y middlewares (`backend/app/main.py`, `backend/app/core/middleware.py`)

- CORS estricto con `allow_credentials=True` y orígenes explícitos. En desarrollo Vite proxea `/api`, por lo que el navegador ve un único origen.
- Documentación OpenAPI en `/api/docs` y `/api/openapi.json`, deshabilitada en producción.
- Cada respuesta, incluidos los errores 500, lleva:
  - `X-Correlation-ID`: se respeta el valor entrante solo si cumple `^[A-Za-z0-9._-]{1,128}$` (evita inyección en logs); si no, se genera un UUID.
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security: max-age=31536000; includeSubDomains`.
- Errores en RFC 7807 (`application/problem+json`) con `type`, `title`, `status`, `detail`, `instance` y `correlation_id`. Los 500 nunca exponen el mensaje interno.

#### 5.3 Diagnóstico de salud (`backend/app/modules/health/router.py`)

`GET /api/health` ejecuta un `SELECT 1` real y responde:

```json
{ "status": "ok", "db": "up", "time_utc": "2026-10-25T13:37:47.795972Z" }
```

Si la base no responde: `"status": "degraded", "db": "down"`. El detalle técnico del fallo va al log, nunca a la respuesta. El endpoint de salud es de infraestructura y no se versiona; las rutas de negocio se publican bajo `/api/v1` a partir de la Fase 1.

---

### 6. Protocolo de Gobernanza para Agentes (`AGENTS.md`)

`AGENTS.md`, en la raíz del repositorio, contiene el playbook de fases y el protocolo obligatorio para agentes y desarrolladores:

1. **Integridad de reglas financieras:** prohibido deducir, extrapolar o inventar fórmulas de aportes, escalas o tasas. Todo cálculo se basa en especificaciones aprobadas por la Caja o en parámetros vigentes de la base. Parámetros no definidos se marcan `TODO(negocio)` con valores de ejemplo explícitos. Prohibido `float` para montos.
2. **Aislamiento de datos sensibles:** prohibido interactuar con bases productivas durante desarrollo o pruebas; prohibidas credenciales reales en el código; todo correo de desarrollo y test va a Mailpit; se trabaja con fixtures sintéticos.
3. **Seguridad en servidor (`SEC-01`):** cada acción valida permisos en el backend; toda acción crítica genera un registro inmutable de auditoría (`SEC-03`) con autor, UTC, valor anterior y nuevo.
4. **Requisitos de entrega por fase:** cobertura mínima del 85% en código de negocio; pruebas negativas de autorización (HTTP 403); migraciones reversibles (`upgrade` y `downgrade`, verificadas en CI); contrato OpenAPI sin inconsistencias de tipado.

---

### 7. Guía de Ejecución Local y Verificación

```bash
# 1. Dependencias del sistema (macOS)
brew install postgresql@16 libmagic pango gdk-pixbuf libffi mailpit pre-commit

# 2. Dependencias del proyecto y backend/.env
make install

# 3. Rol, bases y extensiones
make db

# 4. Migraciones
make migrate

# 5. Levantar Mailpit + backend + frontend
make dev

# 6. Verificar salud y conectividad con la base
curl -i http://localhost:8000/api/health

# 7. Tests y linters
make test
make lint
```

---

### 8. Criterios de Aceptación del Módulo 1

1. **Tipado financiero exacto:** ninguna columna ni lógica monetaria usa coma flotante. Verificado por test (`tests/test_guards.py`) y por el hook de pre-commit/CI.
2. **Inicialización segura:** el backend no arranca si falta o es inválida una variable crítica (`DATABASE_URL`, `PUBLIC_WEB_URL`, `JWT_SECRET`).
3. **Diagnóstico conectivo:** `GET /api/health` valida la conectividad real con PostgreSQL (`db: up`).
4. **Encabezados de seguridad activos:** todas las respuestas, incluidas las de error, devuelven `X-Correlation-ID`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` y `Strict-Transport-Security`. Verificado por `tests/test_security_headers.py`.
5. **Gobernanza operativa:** `AGENTS.md` incorporado; CI verifica lint, tipos, guardas, migraciones reversibles y tests en cada push.
6. **Entorno reproducible sin Docker:** `make db && make migrate && make dev` deja la suite operativa en una máquina limpia con los requisitos de la sección 7.
