#!/usr/bin/env bash
# Prueba de restauración: carga el último backup en una base aparte, la compara con lo que dice el
# dump y la borra. No toca la base en uso. Corre semanal (deploy/instalar-cron.sh) y a mano:
#   /opt/suite-notarial/deploy/probar-restauracion.sh
set -euo pipefail
cd /opt/suite-notarial
COMPOSE="docker compose --env-file deploy/.env.server -f deploy/compose.server.yml"
DESTINO=/opt/backups/suite-notarial
PRUEBA=restauracion_prueba
PSQL="$COMPOSE exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -qtA"

BASE=$(ls -1t "$DESTINO"/base-*.dump 2>/dev/null | head -1 || true)
[[ -n "$BASE" ]] || { echo "$(date -Is) ERROR: no hay backups en $DESTINO"; exit 1; }
FECHA=${BASE##*/base-}; FECHA=${FECHA%.dump}
ARCHIVOS="$DESTINO/archivos-$FECHA.tar.gz"

# El mismo candado que backup.sh: no probar un backup a medio escribir.
exec 9>"$DESTINO/.lock"
flock -n 9 || { echo "$(date -Is) ERROR: hay un backup en curso"; exit 1; }

# Sin suma de control no hay prueba: un backup sin verificar no cuenta como bueno.
[[ -f "$DESTINO/suma-$FECHA.sha256" ]] \
  || { echo "$(date -Is) ERROR: falta la suma de control del backup $FECHA"; exit 1; }
(cd "$DESTINO" && sha256sum --quiet -c "suma-$FECHA.sha256") \
  || { echo "$(date -Is) ERROR: el backup $FECHA no coincide con su suma de control"; exit 1; }

# La copia tiene datos reales: que no quede en el servidor aunque la prueba falle.
limpiar() {
  $PSQL -d postgres -c "DROP DATABASE IF EXISTS $PRUEBA WITH (FORCE)" </dev/null >/dev/null \
    || echo "$(date -Is) ERROR: no se pudo borrar la base $PRUEBA: borrarla a mano"
}
existe=$($PSQL -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$PRUEBA'" </dev/null)
[[ -z "$existe" ]] || echo "$(date -Is) AVISO: quedó la base $PRUEBA de una prueba anterior: se borra"
trap limpiar EXIT
limpiar
# Solo postgres entra a la copia: sin CONNECT para el resto y sin los permisos del dump.
$PSQL -d postgres -c "CREATE DATABASE $PRUEBA" </dev/null
$PSQL -d postgres -c "REVOKE CONNECT, TEMPORARY ON DATABASE $PRUEBA FROM PUBLIC" </dev/null
$COMPOSE exec -T postgres pg_restore -U postgres -d "$PRUEBA" --no-owner --no-privileges \
  --exit-on-error < "$BASE"

version=$($PSQL -d "$PRUEBA" -c "SELECT version_num FROM alembic_version" </dev/null)
tablas=$($PSQL -d "$PRUEBA" -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" </dev/null)
filas=$($PSQL -d "$PRUEBA" -c "SELECT
  (SELECT count(*) FROM security_users) || ' usuarios, ' ||
  (SELECT count(*) FROM padron_escribanos) || ' escribanos, ' ||
  (SELECT count(*) FROM audit_security_logs) || ' registros de auditoría'" </dev/null)
[[ -n "$version" && "$tablas" -gt 0 ]] || { echo "$(date -Is) ERROR: restauración incompleta"; exit 1; }

# Los archivos subidos: que el tar se lea entero y cuántos trae.
cantidad=0
if [[ -f "$ARCHIVOS" ]]; then
  cantidad=$(tar -tzf "$ARCHIVOS" | grep -vc '/$' || true)
fi
echo "$(date -Is) restauración OK ($FECHA): migración $version, $tablas tablas, $filas, $cantidad archivos"
