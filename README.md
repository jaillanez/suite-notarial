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
| 2 | Padrón: escribanos, matrículas, registros, cargos y circunscripciones | Completa |
| 3 | Motor paramétrico de aportes: conceptos, vigencias versionadas y cálculo | Completa |
| 4 | DDJJ, liquidación y boletas con PDF, QR y verificación pública | Completa |
| 5 | Pagos: comprobantes y mesa de conciliación de Tesorería | Completa |
| 6 | Reportes con paginación en servidor y exportación XLSX/CSV con paridad de totales | Completa |
| 7 | Sitio institucional: novedades, autoridades y documentos oficiales con integridad verificada | Completa |
| 8 | Préstamos: líneas, simulación, otorgamiento con cuatro ojos, garantes y cobro de cuotas | Completa |
| 9 | IA asistencial: actos desde la minuta y alta desde el DNI, siempre ratificados por una persona | Completa |
| 10 | Migración: formato de intercambio, simulacros con cuadratura al centavo, conformidad, carga definitiva y reversa ensayada | En revisión |

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
brew install postgresql@16 libmagic pango gdk-pixbuf libffi mailpit pre-commit tesseract tesseract-lang
```

- `tesseract` lee minutas escaneadas y el dorso del DNI; `tesseract-lang` agrega el español (sin
  él usa inglés y lee peor las tildes). Sin Tesseract, la IA sigue funcionando con PDF con texto,
  texto pegado y el código de barras del DNI.

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

También carga los **parámetros 2026 relevados del sistema en uso** (aporte por escrituras,
fijos por acto, mínimo mensual, médico asistencial y tasa de mora; ver
`backend/app/modules/parametros/sistema_actual.py`). La tasa de mora figura «a confirmar»
porque la pantalla no indica su unidad. Además siembra un padrón sintético: una circunscripción, tres registros y cinco escribanos
(el primero vinculado a la cuenta `escribano@suite-notarial.example`). Son datos inventados.

Los roles con 2FA obligatorio entran directo a *Seguridad de la cuenta* hasta activarlo. En
desarrollo local se puede apagar esa exigencia con `MFA_ENFORCED=false` en `backend/.env`, para
no reactivarlo tras cada `make reset-dev`; la configuración rechaza ese valor fuera de
development/test y los tests siempre corren con el 2FA exigido. Para
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
| `make ensayo-corte` | Ensayo cronometrado de carga definitiva y reversa en `suite_notarial_ensayo` (`registros=` y `periodos=` para el volumen) |
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
| `CAJA_NOMBRE` / `CAJA_CUIT` / `CAJA_DOMICILIO` / `CAJA_CONTACTO` | Datos de la Caja impresos en la boleta |
| `BANCO_NOMBRE` / `BANCO_CUENTA` / `BANCO_CBU` / `BANCO_ALIAS` | Cuenta recaudadora impresa en la boleta. Solo en el `.env` de cada entorno; sin CBU la boleta dice «Datos bancarios a confirmar» |
| `CMS_MAX_DOC_MB` | Tamaño máximo de los documentos oficiales que se publican en el sitio (25) |
| `UPLOAD_DIR` / `MAX_UPLOAD_MB` | Almacenamiento de comprobantes, fuera del webroot (10 MB). También es el tope de los archivos que lee la IA |
| `IA_TESSERACT_CMD` / `IA_OCR_IDIOMAS` | Binario de Tesseract y idiomas preferidos (`spa+eng`; se usan los instalados) |
| `IA_OCR_TIMEOUT_S` / `IA_OCR_CONCURRENCIA` | Tiempo máximo de una lectura (30 s) y lecturas simultáneas (2); con la cola llena se responde 503 |
| `MIGRACION_SIMULACROS_MINIMOS` | Simulacros cuadrados exigidos antes de la carga definitiva (3) |
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
- **Estados de matrícula:** ACTIVO, SUSPENDIDO, CESANTE, JUBILADO, FALLECIDO. Cada cambio exige
  motivo y fecha efectiva y queda en `padron_historial_estados`, inmutable. Transiciones:

  | Desde | Puede pasar a |
  |-------|---------------|
  | Activo | Suspendido, Cesante, Jubilado, Fallecido |
  | Suspendido | Activo, Cesante, Jubilado, Fallecido |
  | Cesante | Activo (reincorporación, con resolución obligatoria), Jubilado, Fallecido |
  | Jubilado | Fallecido |
  | Fallecido | — |

  Los estados definitivos (Cesante, Jubilado, Fallecido) exigen cerrar antes los cargos
  vigentes y suspenden la cuenta de autogestión (la reactiva un administrador).
- **Autogestión según la matrícula:** sin matrícula ACTIVA (p. ej. suspendido) la cuenta queda en
  solo consulta: ve sus DDJJ y boletas y puede adjuntar comprobantes de pago, pero no presentar
  DDJJ. Se recalcula en cada request: al volver a ACTIVO recupera todo sin intervención.
- **Registros y cargos:** un titular vigente por registro y un cargo vigente por escribano
  (índices únicos parciales). El registro pasa a *con titular* al designarlo y a *vacante* al
  cerrar su titularidad. Los cargos se cierran con fecha y motivo.
- **Sin borrado físico (INM):** la app no tiene DELETE ni TRUNCATE sobre las tablas del padrón y un
  trigger lo impide también al dueño. Toda alta, edición, cambio de estado o cargo se audita.
- **Endpoints:** `/api/v1/padron/{escribanos,registros,circunscripciones,departamentos,cargos}`.

## Motor paramétrico (Fase 3)

- **Conceptos** de cuatro tipos: porcentaje sobre escrituras (con mínimo y tope opcionales),
  monto fijo por acto, monto fijo mensual y tasa de mora (mensual o anual, con días de gracia).
  Cada uno tiene **vigencias** con fecha desde y hasta (o sin fin).
- **Relevado del sistema actual:** la fórmula `aporte = base × 0,40 %` acotada por mínimo y tope
  reproduce al centavo las 351 escrituras del reporte de agosto-septiembre 2026, y la boleta
  09/2026 se reconstruye con el mínimo mensual (excedente = protocolos − mínimo) más el aporte
  médico. Las capturas de origen están en `Docs/privado/` (fuera del repositorio).
- **Nunca se sobreescribe:** una vigencia nueva es una fila nueva. Un trigger impide modificar o
  borrar sus valores; solo se cierra la fecha hasta de una vigencia abierta cuando se aprueba la
  que la reemplaza (el día anterior a su inicio), y queda auditado.
- **Sin solapamiento:** una restricción de exclusión (GiST sobre rangos de fechas) impide en la
  base que dos vigencias aprobadas del mismo concepto se superpongan; la API lo rechaza antes con
  un mensaje claro.
- **Cuatro ojos:** quien propone una vigencia no puede aprobarla (permiso `parameters:approve`,
  verificado en la API y como CHECK en la base). Toda propuesta, aprobación, rechazo o cierre
  queda en la auditoría.
- **Resolución por fecha:** `get_vigencia(codigo, fecha)` devuelve la única vigencia aprobada
  aplicable o un error explícito; las boletas guardarán su id (SNAP).
- **Cálculo exacto:** montos `Numeric(15,2)`, tasas `Numeric(18,4)` expresadas en %, todo en
  `Decimal` y transmitido como texto (nunca como número de punto flotante).
- **Pendiente de negocio (`TODO(negocio)`):** unidad de la tasa de interés («34»: se tomó como
  anual), interés simple o compuesto y base de días, días de gracia y desde cuándo corre la mora;
  y la resolución que respalda cada valor (el sistema actual no la muestra).

## DDJJ y boletas (Fase 4)

- **Una DDJJ por registro y período** con los actos de todos sus escribanos (titular, adscriptos,
  a cargo). Cada acto lleva protocolo, número de escritura, fecha dentro del período, naturaleza y
  categoría: escritura con valor (porcentaje de la base con mínimo y tope), acta o poder, otro
  acto (montos fijos) o sin efecto (no aporta). Los actos de un borrador se quitan con motivo.
- **Controles del libro de protocolo** (numeración correlativa por registro, protocolo y año):
  un número de escritura repetido en cualquier DDJJ del año no se puede cargar; folio repetido
  (salvo con la escritura contigua) y folio o fecha fuera de orden se avisan; los números
  salteados del año se listan en la ficha para declararlos «sin efecto». Mientras se carga un
  acto, el formulario muestra el aporte estimado y los avisos. `TODO(negocio)`: confirmar que la
  numeración vuelve a 1 cada año.
- **Cálculo en el servidor**, con las vigencias del primer día del período:
  protocolos = suma de aportes; excedente = protocolos − aporte mínimo (si es positivo); total en
  término = mínimo + excedente + aporte médico; mora sobre el total en término si se paga después
  del vencimiento. Reproduce al centavo la boleta 1069 del sistema actual.
- **Presentar** congela el aporte y la vigencia de cada acto y emite la boleta en la misma
  transacción (SNAP): un cambio posterior de parámetros no altera nada emitido. Una **boleta
  nueva** para otra fecha de pago anula la pendiente y solo recalcula la mora. Una DDJJ presentada
  se corrige con una **rectificativa** (copia editable de los actos; la original queda como
  antecedente y su boleta pendiente se anula).
- **Boleta oficial en PDF** (WeasyPrint): número correlativo, desglose, datos bancarios desde la
  configuración, QR a `/verificar/{código}`, Code128 y huella SHA-256 de los datos impresos.
  `/verificar/{código}` es público y muestra lo mínimo (número, registro, período, total, estado)
  e indica si la boleta supera el control de integridad.
- **Vencimientos:** calendario por período (`make seed-dev` carga el de 2026); lo fija
  Administración y queda fijo en cuanto el período tiene boletas.
- **Inmutable en la base:** sin DELETE/TRUNCATE; actos solo con la DDJJ en borrador; una DDJJ
  presentada solo pasa a rectificada; de una boleta solo cambia el estado.
- **Acceso:** el escribano opera las DDJJ de los registros donde tiene cargo vigente y ve las de
  los meses en que lo tuvo; la Caja consulta todo y puede cargar y presentar por el registro.
- **Pendiente de negocio (`TODO(negocio)`):** si el mínimo es por registro, cuántos aportes
  médicos corresponden, plazo de validez de la boleta, formato de código de barras del banco y
  rectificación de una DDJJ ya paga (Fase 5).

## Pagos y conciliación (Fase 5)

- **Adjuntar no es pagar (PAGO):** el escribano adjunta el comprobante de la transferencia a su
  boleta pendiente y queda *en revisión*. La boleta pasa a pagada solo cuando Tesorería lo
  confirma; un trigger lo exige también en la base.
- **Archivos (MIME):** PDF, PNG o JPG detectados por *magic bytes* (no por la extensión), hasta
  `MAX_UPLOAD_MB`, guardados con nombre UUID y permisos 0600 en `UPLOAD_DIR`, fuera de lo que
  sirve el frontend. Se guarda su SHA-256 y se verifica cada vez que se muestra: un archivo
  alterado no se entrega y queda auditado.
- **Mesa de conciliación** (`/tesoreria/conciliacion`, permiso `comprobantes:verify`): bandeja
  por orden de llegada, visor del comprobante junto a la boleta y la diferencia entre lo
  declarado y el total. Confirmar exige el importe y la fecha de acreditación del extracto (solo
  el total exacto) y, si se acreditó después de la fecha de pago, observaciones. Rechazar exige
  motivo y avisa por correo al escribano.
- **Asientos inmutables** en `pagos_conciliaciones`; la aplicación no puede modificarlos ni
  borrarlos. Mientras un comprobante está en revisión, la boleta no se reemite ni se rectifica.
- **Pendiente de negocio (`TODO(negocio)`):** pagos parciales o con diferencia, mora por
  acreditación tardía, rectificación de una DDJJ paga y más de una cuenta recaudadora.

## Reportes (Fase 6)

- **Paridad pantalla ↔ archivo (REP):** cada reporte es una sola consulta con columnas y filtros
  declarados. La grilla (paginada en el servidor), los totales y las exportaciones XLSX y CSV
  usan la misma consulta, filtros y orden; los totales suman todas las filas filtradas.
- **Reportes:** padrón de escribanos, boletas emitidas, pagos y conciliaciones, recaudación por
  período y registro de auditoría, cada uno con su permiso (`/reportes`).
- **Grilla:** cabecera y totales fijos, columnas configurables (algunas ocultas por defecto, se
  recuerdan por navegador) y lista apilada en celular, sin scroll horizontal infinito.
- **Exportación:** XLSX con importes `Decimal` exactos, autofiltro y fila de totales; CSV es-AR
  (`;`, coma decimal, UTF-8 con BOM). Fechas en hora de San Juan, protección contra inyección de
  fórmulas y registro de cada exportación en la auditoría (máximo 50.000 filas).

## Sitio institucional (Fase 7)

- **Público sin sesión** en `/sitio`: novedades, autoridades vigentes y documentos oficiales
  (estados contables, memorias, resoluciones) por tipo y ejercicio, con descarga, huella SHA-256
  y versiones anteriores. Administración en `/cms` con el permiso `cms:publish`.
- **Solo PDFs reales:** se valida cabecera, tipo, estructura (pypdf), que no esté cifrado y que
  no tenga contenido activo. Una página HTML disfrazada de `.pdf` se rechaza al subirla.
- **Enlace permanente:** reemplazar el archivo crea una versión nueva (con motivo público); el
  enlace canónico pasa a servirla y las anteriores quedan accesibles. Nada se borra y las
  versiones no se modifican (triggers).
- **Integridad al servir:** cada descarga verifica la huella; un archivo alterado no se entrega
  y queda una alerta CRITICAL en la auditoría. Toda publicación y cambio se audita.

## Préstamos (Fase 8)

- **Cuadros exactos:** sistema francés (cuota constante) y alemán (capital constante) con
  `Decimal`; la última cuota cierra el saldo en $ 0,00 y las amortizaciones suman el capital.
- **Tope de afectación:** la cuota más alta más las cuotas de los otros préstamos vigentes no
  pueden superar el porcentaje del ingreso neto que fija la línea (redondeo hacia arriba).
- **Garante:** matrícula activa, sin mora propia, sin garantizar préstamos en mora y sin deuda de
  aportes con la Caja.
- **Cuatro ojos:** la Caja carga la solicitud y la otorga otra persona (Administración), que no
  puede ser titular ni garante; al otorgar se reevalúa y se genera el plan inmutable. Tesorería
  cobra las cuotas en orden y el préstamo se cancela con la última.
- **Valores de negocio:** las líneas de `make seed-dev` son de ejemplo («a confirmar»); tasas,
  plazos y topes los fija el Directorio (`TODO(negocio)`, igual que punitorios y pagos parciales).

## IA asistencial (Fase 9)

- **Human in Command:** la IA solo sugiere. Toda lectura queda `SUGERIDO_POR_IA` y no crea nada;
  el acto o el escribano existen recién cuando la misma persona que pidió la lectura revisa,
  corrige si hace falta, tilda la revisión y confirma. La ratificación pasa por los servicios de
  siempre (`agregar_acto`, `create_escribano`): mismas validaciones, permisos y auditoría, en una
  sola transacción. La IA no propone aportes, no presenta declaraciones ni mueve saldos.
- **Minuta → acto de la DDJJ** (`/ddjj/:id/minuta`): PDF con texto, foto (OCR) o texto pegado.
  Motor de reglas explicable: cada dato trae la regla, la confianza y el fragmento que lo
  respalda. Alertas: cifras y letras distintas (número y monto), fecha fuera del período o
  futura, número ya declarado, CUIT inválidos, moneda extranjera, menor sin representación,
  registro distinto y cargo distinto. El autorizante se busca en el equipo del registro
  (titular, adscriptos y a cargo) por matrícula, apellido o el cargo con que se presenta.
- **DNI → alta en el padrón** (Nuevo escribano): código PDF417 del frente o MRZ del dorso con sus
  cuatro dígitos de control. El CUIL se propone con el algoritmo de AFIP y confianza baja.
- **Datos:** todo corre en el servidor (Tesseract y zxing locales). El documento no se guarda.
  La tabla `ia_sugerencias` no se borra ni se modifica (trigger) y guarda solo regla, confianza y
  una huella HMAC de cada valor, sin datos personales ni texto de la minuta; alcanza para
  auditar qué propuso el motor y qué corrigió la persona (reporte «Sugerencias de IA»).
- **Fuera de alcance:** la comparación facial 1:1 son datos biométricos sensibles (Ley 25.326):
  `TODO(negocio)` decidir si se implementa y con qué resguardos. También queda para la Caja el
  plazo de conservación de los metadatos de las sugerencias.

## Migración y puesta en marcha (Fase 10)

- **Lote de extracción** en un [formato de intercambio](Docs/formato-intercambio-migracion.md) propio (el sistema anterior todavía no fue auditado: D-03), con `control.csv` de totales del origen y una tabla de homologación de códigos.
- **Corridas** por consola (`python -m app.modules.migracion.cli`): validación con observaciones por fila (sin datos personales), carga en una sola transacción y **cuadratura al centavo**: control = leído = cargado + rechazado, y el mismo saldo por registro en origen y destino. Nada se redondea ni se compensa.
- **Simulacros** que se revierten y dejan informe. La **carga definitiva** exige 3 simulacros cuadrados del mismo lote y la misma homologación, la conformidad de Tesorería y de Caja (personas distintas, en *Migración*) y una tabla que no sea la de ejemplo. Además tiene que cuadrar por sí misma y rechazar lo mismo que lo firmado. Una sola por base.
- **Padrón** a las tablas operativas; **boletas y pagos** a un histórico de solo lectura (no se inventan vigencias ni conciliaciones). La deuda histórica impaga cuenta para garantes; reporte «Boletas del sistema anterior».
- **Reversa ensayada:** `make ensayo-corte` corre todo el circuito sobre `suite_notarial_ensayo` y cronometra respaldo, carga y reversa contra el objetivo de 30 minutos (también corre en los tests). Procedimiento completo en el [manual de corte y reversa](Docs/corte-y-reversa.md).

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
