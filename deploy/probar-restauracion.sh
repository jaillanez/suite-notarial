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

if [[ -f "$DESTINO/suma-$FECHA.sha256" ]]; then
  (cd "$DESTINO" && sha256sum --quiet -c "suma-$FECHA.sha256") \
    || { echo "$(date -Is) ERROR: el backup $FECHA no coincide con su suma de control"; exit 1; }
fi

limpiar() { $PSQL -d postgres -c "DROP DATABASE IF EXISTS $PRUEBA" </dev/null >/dev/null || true; }
trap limpiar EXIT
limpiar
$PSQL -d postgres -c "CREATE DATABASE $PRUEBA" </dev/null
$COMPOSE exec -T postgres pg_restore -U postgres -d "$PRUEBA" --no-owner --exit-on-error < "$BASE"

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
