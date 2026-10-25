# Suite Notarial — Caja Notarial de San Juan

Suite integral de la Caja Notarial de San Juan: padrón de escribanos, motor paramétrico de aportes,
DDJJ y boletas, pagos y conciliación, reportes, sitio institucional, préstamos e IA asistencial.

- **Playbook de construcción por fases:** [`AGENTS.md`](AGENTS.md) (copia en `PLAN_CONSTRUCCION.md`).
- **Producto y diseño:** [`PRODUCT.md`](PRODUCT.md), [`DESIGN.md`](DESIGN.md).
- **Especificación funcional por módulo:** [`Docs/`](Docs/).

## Estado

| Fase | Alcance | Estado |
|------|---------|--------|
| 0 | Bootstrap y cimientos | Completa |
| 1 | IAM & RBAC: login, 2FA, sesiones, recuperación de clave, usuarios y auditoría | Completa |
| 2 | Padrón: escribanos, matrículas, registros, cargos y circunscripciones | En revisión |
| 3–10 | Ver `AGENTS.md` | Pendiente |

## Stack

| Capa | Tecnología |
|------|------------|
| Backend | Python 3.12+ · FastAPI · SQLAlchemy 2 async · asyncpg · Alembic · Pydantic Settings |
| Base de datos | PostgreSQL 16+ (local, sin Docker) con `pgcrypto` |
| Frontend | React 19 · TypeScript estricto · Vite · Tailwind CSS v4 · TanStack Query/Table · Axios |
| Correo (dev) | Mailpit local |
| Calidad | ruff · mypy (strict) · pytest · ESLint · Prettier · tsc · Vitest · pre-commit |

## Estructura

```
backend/
  app/
    core/      config tipada, db, logging JSON, errores RFC 7807, seguridad
    common/    dependencias compartidas, helpers monetarios (Decimal)
    db/        Base declarativa, mixins UUID/timestamps, registro de modelos
    modules/   un paquete por módulo de negocio (health/, iam/, padron/, ...)
  alembic/     migraciones
  tests/
frontend/      Vite + React + TS
scripts/       bootstrap_db.sh, dev.sh, hooks de calidad
Docs/          especificación funcional y técnica
```

## Requisitos (macOS)

```bash
brew install postgresql@16 libmagic pango gdk-pixbuf libffi mailpit pre-commit
```

- Python 3.12 o superior y Node 20 LTS o superior.
- PostgreSQL corriendo localmente; el usuario de macOS debe poder conectarse con `psql -d postgres`.
- `python-magic` y `weasyprint` cargan librerías nativas de Homebrew. El `Makefile` exporta
  `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`; si corrés comandos de Python fuera de `make`,
  exportala vos.

## Arranque en limpio

```bash
make install    # venv + deps backend, npm ci, hooks de pre-commit; crea backend/.env desde .env.example
make db         # roles suite_owner / suite_app y bases suite_notarial / suite_notarial_test (idempotente)
make migrate    # aplica migraciones con el rol dueño
make seed-dev   # usuarios de demostración (solo development)
make dev        # Mailpit + API + frontend
```

Después de `make install`, completá en `backend/.env` los secretos propios:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                 # JWT_SECRET
python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"  # DATA_ENCRYPTION_KEY
```

y una `DEV_SEED_PASSWORD` que cumpla la política (10+ caracteres, mayúscula, minúscula, número y
símbolo). Si venís de la Fase 0, las bases eran del rol `suite_app`: borralas
(`psql -d postgres -c "DROP DATABASE suite_notarial"` y lo mismo para `suite_notarial_test`) y
corré `make db migrate` de nuevo.

### Usuarios de demostración

`make seed-dev` crea una cuenta por rol, todas con la contraseña `DEV_SEED_PASSWORD`:

| Rol | Correo | 2FA |
|-----|--------|-----|
| Administración del sistema | `admin@suite-notarial.example` | Obligatorio |
| Administración de Caja | `caja@suite-notarial.example` | Obligatorio |
| Tesorería | `tesoreria@suite-notarial.example` | Obligatorio |
| Auditoría | `auditor@suite-notarial.example` | Obligatorio |
| Escribano | `escribano@suite-notarial.example` | Opcional |

Además siembra un padrón sintético: una circunscripción, tres registros y cinco escribanos
(el primero vinculado a la cuenta `escribano@suite-notarial.example`). Son datos inventados.

Los roles con 2FA obligatorio entran directo a *Seguridad de la cuenta* hasta activarlo. Para
producción, el primer administrador se crea con
`make create-admin email=... cuit=... name="..."` (pide la contraseña por consola).

### Puertos

| Servicio | URL |
|----------|-----|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000/api/health · docs en `/api/docs` |
| Mailpit (UI) | http://localhost:8025 · SMTP en `localhost:1025` |

Si otro proyecto ocupa esos puertos: `make dev API_PORT=8010 WEB_PORT=5183`. En desarrollo Vite
proxea `/api` al backend, así que el navegador ve un único origen y las cookies HttpOnly viajan sin CORS.

## Comandos

| Comando | Qué hace |
|---------|----------|
| `make dev` | Levanta Mailpit, backend (reload) y frontend |
| `make backend` / `make frontend` / `make mailpit` | Cada servicio por separado |
| `make migrate` | `alembic upgrade head` |
| `make revision m="descripcion"` | Genera una migración con autogenerate |
| `make seed-dev` / `make reset-dev` | Usuarios de demostración / recrear el esquema local desde cero |
| `make create-admin email=... cuit=... name="..."` | Alta del primer administrador |
| `make e2e` | Flujo punta a punta de la Fase 1 contra `make dev` y Mailpit |
| `make test` | pytest + Vitest |
| `make lint` | ruff, mypy, ESLint, Prettier, tsc |
| `make fmt` | Formatea backend y frontend |

## Variables de entorno

Definidas y tipadas en `backend/app/core/config.py`; plantilla en `backend/.env.example`.

| Variable | Descripción |
|----------|-------------|
| `ENVIRONMENT` | `development` · `test` · `staging` · `production` |
| `DATABASE_URL` | Rol de la aplicación (`suite_app`): DML, sin privilegios de dueño |
| `MIGRATIONS_DATABASE_URL` | Rol dueño del esquema (`suite_owner`), solo para migraciones |
| `PUBLIC_WEB_URL` | Base de todos los enlaces enviados por mail (SEC-04). Fuera de dev/test no puede ser un host privado |
| `CORS_ORIGINS` | Orígenes permitidos (JSON) |
| `JWT_SECRET` | Secreto de firma, mínimo 32 caracteres |
| `JWT_ACCESS_TTL_MIN` / `JWT_REFRESH_TTL_DAYS` | Vigencia del access token (15 min) y del refresh (7 días) |
| `DATA_ENCRYPTION_KEY` | AES-256 en base64 (32 bytes) para secretos en reposo: semillas TOTP y clave HMAC de códigos de recuperación |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCK_MINUTES` | Bloqueo temporal tras intentos fallidos (5 / 15) |
| `MFA_PENDING_TTL_MIN` | Tiempo para completar el segundo paso del ingreso (5) |
| `COOKIE_SECURE` / `COOKIE_DOMAIN` | Atributos de la cookie de sesión (`COOKIE_SECURE=true` en producción) |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | Correo saliente (Mailpit en dev) |
| `SMTP_SECURITY` / `SMTP_USER` / `SMTP_PASSWORD` | `none` solo en dev/test; fuera de eso `starttls` o `tls` obligatorio |
| `DEV_SEED_PASSWORD` | Solo desarrollo: contraseña de los usuarios de demostración |
| `PASSWORD_RESET_TTL_MIN` | Vigencia del token de recuperación (30) |
| `UPLOAD_DIR` / `MAX_UPLOAD_MB` | Almacenamiento de comprobantes, fuera del webroot (10 MB) |
| `LOG_LEVEL` | Nivel de logging (JSON a stdout) |

## Reglas innegociables

Resumen operativo en [`AGENTS.md`](AGENTS.md#1-reglas-innegociables-resumen-operativo--aplican-en-todas-las-fases).
Ya aplicadas:

- **FIN:** dinero y tasas solo con `Decimal` vía `app/common/money.py` (`ROUND_HALF_UP`); un test y un hook
  de pre-commit bloquean `float` en módulos monetarios.
- **API:** todos los errores salen como `application/problem+json` (RFC 7807), con `correlation_id`.
- **SEC-01:** cada endpoint protegido usa `Depends(require_permissions(...))`, que lee los permisos
  de la base en cada request y audita los rechazos. Ocultar en React es solo experiencia de uso.
- **SEC-04:** los enlaces de correo salen de `PUBLIC_WEB_URL`; un test rechaza URLs privadas en plantillas.
- **AUD:** `audit_security_logs` guarda actor, UTC, IP, valor anterior y nuevo. El rol de la app no
  tiene UPDATE/DELETE/TRUNCATE sobre la tabla y un trigger lo impide también al dueño.

## Padrón notarial (Fase 2)

- **Personas y escribanos:** los datos personales viven solo en `padron_personas`; la matrícula en
  `padron_escribanos`. CUIT y matrícula únicos; el CUIT se valida con el dígito verificador de
  AFIP (incluida la reasignación a 23/33 cuando el cálculo da 10).
- **Estados de matrícula:** ACTIVO, SUSPENDIDO, CESANTE, JUBILADO, FALLECIDO (terminal). Cada
  cambio exige motivo y fecha efectiva y queda en `padron_historial_estados`, inmutable. Los
  estados definitivos exigen cerrar antes los cargos vigentes y suspenden la cuenta de autogestión.
- **Registros y cargos:** un titular vigente por registro y un cargo vigente por escribano
  (índices únicos parciales). El registro pasa a *con titular* al designarlo y a *vacante* al
  cerrar su titularidad. Los cargos se cierran con fecha y motivo.
- **Sin borrado físico (INM):** la app no tiene DELETE ni TRUNCATE sobre las tablas del padrón y un
  trigger lo impide también al dueño. Toda alta, edición, cambio de estado o cargo se audita.
- **Endpoints:** `/api/v1/padron/{escribanos,registros,circunscripciones,departamentos,cargos}`.
- **Pendiente de negocio:** transiciones permitidas entre estados y si SUSPENDIDO debe bloquear
  la autogestión (marcados `TODO(negocio)` en `backend/app/modules/padron/`).

## Seguridad de acceso (Fase 1)

- **Contraseñas:** Argon2id; política de 10+ caracteres con las cuatro clases.
- **Sesión:** cookies `HttpOnly` + `Secure` + `SameSite`. Access JWT de 15 min (`/api`) y refresh
  opaco rotativo de 7 días (`/api/v1/auth`); si un refresh ya usado reaparece, se revoca toda la
  familia de sesiones. Logout, suspensión o cambio de clave cortan el acceso en la request siguiente.
- **CSRF:** los métodos que modifican exigen `X-Requested-With: XMLHttpRequest` y, si el navegador
  informa `Origin`, que sea de la Suite.
- **2FA TOTP:** semilla cifrada con AES-GCM, anti-replay, 10 códigos de recuperación de un solo uso.
  Obligatorio para ADMIN, CAJA, TESORERIA y AUDITOR.
- **Intentos fallidos:** 5 errores de contraseña o de código bloquean la cuenta 15 minutos. Los
  mensajes son siempre genéricos, sin revelar si la cuenta existe.
- **Recuperación de clave:** token de un solo uso, guardado como SHA-256, vence a los 30 minutos,
  viaja en el fragmento de la URL (`#token=`) y la respuesta es idéntica exista o no la cuenta.

## Producción

Nginx como proxy inverso con TLS, cabeceras de seguridad (HSTS, CSP, `X-Content-Type-Options`,
`Referrer-Policy`) y `COOKIE_SECURE=true`. No se usan en desarrollo. El despliegue y el corte se documentan en
`Docs/modulo-11-migracion-datos-puesta-en-marcha.md`.
