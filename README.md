# Suite Notarial — Caja Notarial de San Juan

Suite integral de la Caja Notarial de San Juan: padrón de escribanos, motor paramétrico de aportes,
DDJJ y boletas, pagos y conciliación, reportes, sitio institucional, préstamos e IA asistencial.

- **Playbook de construcción por fases:** [`AGENTS.md`](AGENTS.md) (copia en `PLAN_CONSTRUCCION.md`).
- **Producto y diseño:** [`PRODUCT.md`](PRODUCT.md), [`DESIGN.md`](DESIGN.md).
- **Especificación funcional por módulo:** [`Docs/`](Docs/).

## Estado

| Fase | Alcance | Estado |
|------|---------|--------|
| 0 | Bootstrap y cimientos | En revisión |
| 1–10 | Ver `AGENTS.md` | Pendiente |

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
make db         # crea rol suite_app y bases suite_notarial / suite_notarial_test (idempotente)
make migrate    # aplica migraciones
make dev        # Mailpit + API + frontend
```

Después de `make install`, generá un `JWT_SECRET` propio en `backend/.env`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

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
| `make test` | pytest + Vitest |
| `make lint` | ruff, mypy, ESLint, Prettier, tsc |
| `make fmt` | Formatea backend y frontend |

## Variables de entorno

Definidas y tipadas en `backend/app/core/config.py`; plantilla en `backend/.env.example`.

| Variable | Descripción |
|----------|-------------|
| `ENVIRONMENT` | `development` · `test` · `staging` · `production` |
| `DATABASE_URL` | `postgresql+asyncpg://suite_app:...@localhost:5432/suite_notarial` |
| `PUBLIC_WEB_URL` | Base de todos los enlaces enviados por mail (SEC-04). Fuera de dev/test no puede ser un host privado |
| `CORS_ORIGINS` | Orígenes permitidos (JSON) |
| `JWT_SECRET` | Secreto de firma, mínimo 32 caracteres |
| `JWT_ACCESS_TTL_MIN` / `JWT_REFRESH_TTL_DAYS` | Vigencia de tokens |
| `COOKIE_SECURE` / `COOKIE_DOMAIN` | Atributos de la cookie de sesión (`COOKIE_SECURE=true` en producción) |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | Correo saliente (Mailpit en dev) |
| `PASSWORD_RESET_TTL_MIN` | Vigencia del token de recuperación (30) |
| `UPLOAD_DIR` / `MAX_UPLOAD_MB` | Almacenamiento de comprobantes, fuera del webroot (10 MB) |
| `LOG_LEVEL` | Nivel de logging (JSON a stdout) |

## Reglas innegociables

Resumen operativo en [`AGENTS.md`](AGENTS.md#1-reglas-innegociables-resumen-operativo--aplican-en-todas-las-fases).
Ya aplicadas en la Fase 0:

- **FIN:** dinero y tasas solo con `Decimal` vía `app/common/money.py` (`ROUND_HALF_UP`); un test y un hook
  de pre-commit bloquean `float` en módulos monetarios.
- **API:** todos los errores salen como `application/problem+json` (RFC 7807).
- **SEC-04:** test que rechaza URLs privadas en plantillas de mail.

## Producción

Nginx como proxy inverso con TLS, cabeceras de seguridad (HSTS, CSP, `X-Content-Type-Options`,
`Referrer-Policy`) y `COOKIE_SECURE=true`. No se usan en desarrollo. El despliegue y el corte se documentan en
`Docs/modulo-11-migracion-datos-puesta-en-marcha.md`.
