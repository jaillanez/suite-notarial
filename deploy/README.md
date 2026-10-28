# Instalación en el servidor compartido

La Suite corre en el VPS de suite-turnos, suite-auto y suite-juviar, **independiente** de ellos:
proyecto Docker propio (`suite-notarial`), base PostgreSQL propia en su contenedor, volúmenes,
red interna (`10.77.88.0/24`) y claves propias en `deploy/.env.server`. Lo único compartido es el
Caddy de suite-turnos, que publica el dominio con HTTPS automático.

```
Internet ──HTTPS──> Caddy (suite-turnos) ──> suite-notarial-web (nginx: SPA + /api)
                                                   └──> api (FastAPI) ──> postgres
```

## Primera instalación

```bash
git clone -b main https://github.com/jaillanez/suite-notarial.git /opt/suite-notarial
cd /opt/suite-notarial/deploy
./generar-claves.sh            # crea .env.server con contraseñas y claves internas
nano .env.server               # dominio (PUBLIC_WEB_URL, CORS_ORIGINS) y datos de la Caja
cd .. && ./deploy/deploy.sh    # build, migraciones y arranque
```

Datos de demostración (solo en el servidor de prueba, `ENVIRONMENT=staging`):

```bash
docker compose --env-file deploy/.env.server -f deploy/compose.server.yml \
  run --rm api python -m app.modules.iam.cli seed-dev
```

Primer administrador (pide la contraseña por teclado; nunca va en un comando):

```bash
docker compose --env-file deploy/.env.server -f deploy/compose.server.yml \
  run --rm api python -m app.modules.iam.cli create-admin --email ... --cuit ... --name "..."
```

## Dominio en el Caddy compartido

En el servidor, como root:

```bash
bash /opt/suite-notarial/deploy/agregar-a-caddy.sh DOMINIO
```

El script parte de la configuración que el Caddy tiene **en ejecución**, guarda una copia, agrega
solo el bloque de la Suite, lo valida y recién entonces lo aplica. No hay que editar el Caddyfile a
mano: un editor que reemplaza el archivo deja al contenedor leyendo una copia vieja.

## Actualizar

```bash
cd /opt/suite-notarial && ./deploy/deploy.sh
```

## Backups

`deploy/backup.sh` guarda la base y los archivos subidos en `/opt/backups/suite-notarial` (14 días).
Cron sugerido: `15 3 * * * /opt/suite-notarial/deploy/backup.sh >> /var/log/suite-notarial-backup.log 2>&1`.
Guardar una copia de `deploy/.env.server` fuera del servidor: sin `DATA_ENCRYPTION_KEY` no se pueden
leer los 2FA ya activados.
