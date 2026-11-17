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
bash /opt/suite-notarial/deploy/agregar-a-caddy.sh --verificar   # solo compara, no cambia nada
bash /opt/suite-notarial/deploy/agregar-a-caddy.sh DOMINIO
```

La autoridad es la configuración que el Caddy tiene **en ejecución** (se la pide a su API de
administración). Antes de cambiar algo, el script verifica que el Caddyfile del disco produzca
exactamente esa configuración; si difieren, se detiene sin tocar nada y hay que reconciliarlos a
mano. Si coinciden, guarda copias (Caddyfile y configuración en ejecución), agrega solo el bloque de
la Suite, lo valida, lo carga en caliente y lo guarda en el disco. No hay que editar el Caddyfile a
mano: un editor que reemplaza el archivo deja al contenedor leyendo una copia vieja.

## Actualizar

```bash
cd /opt/suite-notarial && ./deploy/deploy.sh
```

## Backups

`deploy/backup.sh` guarda la base (`pg_dump`) y los archivos subidos en `/opt/backups/suite-notarial`
y conserva 14 días (`BACKUP_DIAS`). Antes de darlo por bueno verifica que el dump se pueda leer y
que el `.tar.gz` esté entero, y deja una suma SHA-256 de cada par.

El respaldo y la reversa de la migración (manual de corte, `Docs/corte-y-reversa.md`) usan el
`pg_dump`/`pg_restore` 16 que trae la imagen de la API. En el servidor se corren con un contenedor
de un solo uso y una carpeta del host montada para el archivo:

```bash
cd /opt/suite-notarial
docker compose --env-file deploy/.env.server -f deploy/compose.server.yml run --rm --no-deps -T \
  -v /opt/suite-notarial-ensayo/respaldos:/respaldo api \
  python -m app.modules.migracion.cli respaldo --salida /respaldo/antes-de-la-carga.dump
```

La carpeta tiene que existir y ser del usuario de la imagen (uid 10001).

`deploy/probar-restauracion.sh` restaura el último backup en una base aparte (`restauracion_prueba`),
cuenta tablas, usuarios, escribanos y auditoría, revisa los archivos y borra la base de prueba. No
toca la base en uso.

Programarlos (una vez, como root; se puede repetir):

```bash
/opt/suite-notarial/deploy/instalar-cron.sh
```

Queda el backup todos los días a las 3:15 y la prueba de restauración los domingos a las 4:30, con
registro en `/var/log/suite-notarial-backup.log` (rotación mensual).

**Restaurar de verdad** (pérdida de la base): detener la API, recrear la base y cargar el dump:

```bash
cd /opt/suite-notarial
C="docker compose --env-file deploy/.env.server -f deploy/compose.server.yml"
$C stop api web
$C exec -T postgres pg_restore -U postgres -d suite_notarial --clean --if-exists < /opt/backups/suite-notarial/base-AAAAMMDD-HHMM.dump
$C run --rm -T api tar -C /data -xzf - < /opt/backups/suite-notarial/archivos-AAAAMMDD-HHMM.tar.gz
$C up -d
```

Guardar una copia de `deploy/.env.server` fuera del servidor: sin `DATA_ENCRYPTION_KEY` no se pueden
leer los 2FA ya activados.

TODO(caja): copia fuera del servidor. Los backups viven en el mismo disco que la base; falta definir
con la Caja un destino externo (almacenamiento propio de la Caja) para copiarlos cifrados.

## Botón de pagos Supervielle: cuando lleguen las credenciales

Todo lo que entrega el banco es configuración (`SUPERVIELLE_*` en `deploy/.env.server`); no hace
falta tocar el código. Sin credenciales o sin convenio, el botón no aparece en las boletas.

1. **Cargar y probar** (pide cada valor; los secretos no se muestran ni quedan en el historial):

   ```bash
   cd /opt/suite-notarial && ./deploy/configurar-supervielle.sh
   ```

   Pregunta el ambiente (`pruebas` o `produccion`; en producción, además, las tres direcciones que
   confirme el banco), el convenio, usuario, clave, `client_id`, `client_secret` y
   `x-ibm-client-id`. Reinicia la API, pide un token al banco y, si lo entrega, muestra la
   **dirección de aviso de pagos** para registrar en el banco.

2. **Probar un pago punta a punta** (solo con el ambiente de pruebas del banco):

   ```bash
   C="docker compose --env-file deploy/.env.server -f deploy/compose.server.yml"
   $C exec -T api python -m app.modules.pagos.supervielle_cli probar --publicar-prueba
   ```

   Publica una deuda de $10 y muestra su link: se paga con las tarjetas de prueba del documento
   del banco (p. ej. Visa crédito 4507990000004905, vto. 08/30, CVV 123). Después:

   ```bash
   $C exec -T api python -m app.modules.pagos.supervielle_cli probar --hash HASH
   ```

   Para la prueba completa desde la Suite: emitir una boleta con fecha de pago de mañana o
   posterior, «Pagar con Supervielle», pagar con la tarjeta de prueba y «Ya pagué: verificar». El
   pago aparece en Tesorería → Conciliación.

3. **Comisiones** (una vez): propone los valores de la propuesta del banco; los aprueba otra
   persona desde Parámetros.

   ```bash
   $C exec -T api python -m app.modules.pagos.comisiones_spv proponer --operador EMAIL --desde AAAA-MM-DD
   ```

4. **Tareas programadas**: `deploy/instalar-cron.sh` procesa cada 2 minutos los avisos que llegaron
   durante la pausa entre consultas al banco, y concilia a las 6:10 y 14:10 (recupera los pagos
   cuyo aviso se perdió; registro en `/var/log/suite-notarial-supervielle.log`).
   Antes de cargar las credenciales no hace nada. A mano:
   `$C exec -T api python -m app.modules.pagos.supervielle_cli conciliar --dias 7`.

`python -m app.modules.pagos.supervielle_cli estado` muestra qué falta configurar y a qué ambiente
apunta, sin mostrar secretos.
