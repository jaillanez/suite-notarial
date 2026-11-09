#!/usr/bin/env bash
# Programa los backups (todos los días a las 3:15) y la prueba de restauración (domingos 4:30), y
# rota su registro. Se puede correr las veces que haga falta: reescribe los mismos dos archivos.
#   sudo /opt/suite-notarial/deploy/instalar-cron.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Correr como root."; exit 1; }
LOG=/var/log/suite-notarial-backup.log

cat > /etc/cron.d/suite-notarial <<EOF
# Suite Notarial: copias de seguridad (deploy/instalar-cron.sh). No editar a mano.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 3 * * * root /opt/suite-notarial/deploy/backup.sh >> $LOG 2>&1
30 4 * * 0 root /opt/suite-notarial/deploy/probar-restauracion.sh >> $LOG 2>&1
EOF
chmod 644 /etc/cron.d/suite-notarial

cat > /etc/logrotate.d/suite-notarial <<EOF
$LOG {
  monthly
  rotate 12
  compress
  missingok
  notifempty
}
EOF
touch "$LOG" && chmod 600 "$LOG"
echo "Programado: backup diario 3:15, prueba de restauración los domingos 4:30 (registro en $LOG)."
