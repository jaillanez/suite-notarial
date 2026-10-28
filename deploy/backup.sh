#!/usr/bin/env bash
# Backup diario de la Suite Notarial: base (pg_dump) y archivos subidos (comprobantes y
# documentos del sitio). Guarda en /opt/backups/suite-notarial y conserva 14 días.
# Cron sugerido (root):  15 3 * * *  /opt/suite-notarial/deploy/backup.sh >> /var/log/suite-notarial-backup.log 2>&1
set -euo pipefail
cd /opt/suite-notarial
COMPOSE="docker compose --env-file deploy/.env.server -f deploy/compose.server.yml"
DESTINO=/opt/backups/suite-notarial
FECHA=$(date +%Y%m%d-%H%M)
mkdir -p "$DESTINO" && chmod 700 "$DESTINO"

$COMPOSE exec -T postgres pg_dump -U postgres -Fc suite_notarial > "$DESTINO/base-$FECHA.dump"
$COMPOSE exec -T api tar -C /data -czf - uploads > "$DESTINO/archivos-$FECHA.tar.gz"
# Un dump vacío es un backup fallido: mejor que se note.
[[ -s "$DESTINO/base-$FECHA.dump" ]] || { echo "ERROR: dump vacío"; exit 1; }

find "$DESTINO" -type f -mtime +14 -delete
echo "$(date -Is) backup OK: $(du -sh "$DESTINO/base-$FECHA.dump" | cut -f1) base, $(du -sh "$DESTINO/archivos-$FECHA.tar.gz" | cut -f1) archivos"
