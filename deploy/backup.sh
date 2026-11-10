#!/usr/bin/env bash
# Backup diario de la Suite Notarial: base (pg_dump) y archivos subidos (comprobantes y
# documentos del sitio). Guarda en /opt/backups/suite-notarial y conserva BACKUP_DIAS días (14).
# Lo programa deploy/instalar-cron.sh; deploy/probar-restauracion.sh verifica que se pueda volver.
set -euo pipefail
cd /opt/suite-notarial
COMPOSE="docker compose --env-file deploy/.env.server -f deploy/compose.server.yml"
DESTINO=/opt/backups/suite-notarial
DIAS=${BACKUP_DIAS:-14}
FECHA=$(date +%Y%m%d-%H%M)
mkdir -p "$DESTINO" && chmod 700 "$DESTINO"

# Un solo backup a la vez (el cron y uno manual no se pisan).
exec 9>"$DESTINO/.lock"
flock -n 9 || { echo "$(date -Is) ERROR: ya hay un backup en curso"; exit 1; }

BASE="$DESTINO/base-$FECHA.dump"
ARCHIVOS="$DESTINO/archivos-$FECHA.tar.gz"
# Si algo falla a mitad de camino no queda un backup a medias que parezca bueno.
trap 'rm -f "$BASE.tmp" "$ARCHIVOS.tmp"' EXIT

$COMPOSE exec -T postgres pg_dump -U postgres -Fc suite_notarial </dev/null > "$BASE.tmp"
$COMPOSE exec -T api tar -C /data -czf - uploads </dev/null > "$ARCHIVOS.tmp"

# Un dump vacío o ilegible es un backup fallido: mejor que se note.
[[ -s "$BASE.tmp" ]] || { echo "$(date -Is) ERROR: dump vacío"; exit 1; }
$COMPOSE exec -T postgres pg_restore --list < "$BASE.tmp" > /dev/null \
  || { echo "$(date -Is) ERROR: el dump no se puede leer"; exit 1; }
tar -tzf "$ARCHIVOS.tmp" > /dev/null || { echo "$(date -Is) ERROR: archivo de uploads dañado"; exit 1; }

mv "$BASE.tmp" "$BASE" && mv "$ARCHIVOS.tmp" "$ARCHIVOS"
chmod 600 "$BASE" "$ARCHIVOS"
(cd "$DESTINO" && sha256sum "$(basename "$BASE")" "$(basename "$ARCHIVOS")" > "suma-$FECHA.sha256")

find "$DESTINO" -maxdepth 1 -type f \( -name 'base-*' -o -name 'archivos-*' -o -name 'suma-*' \) \
  -mtime +"$DIAS" -delete
echo "$(date -Is) backup OK: $(du -sh "$BASE" | cut -f1) base, $(du -sh "$ARCHIVOS" | cut -f1) archivos"
