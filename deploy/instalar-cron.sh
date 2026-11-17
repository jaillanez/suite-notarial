#!/usr/bin/env bash
# Programa los backups (todos los días a las 3:15), la prueba de restauración (domingos 4:30) y la
# conciliación del botón Supervielle (avisos pendientes cada 2 minutos; 6:10 y 14:10), y rota sus
# registros. Se puede correr las veces que haga falta: reescribe los mismos dos archivos.
#   sudo /opt/suite-notarial/deploy/instalar-cron.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Correr como root."; exit 1; }
LOG=/var/log/suite-notarial-backup.log
LOG_SPV=/var/log/suite-notarial-supervielle.log
C="docker compose --env-file /opt/suite-notarial/deploy/.env.server -f /opt/suite-notarial/deploy/compose.server.yml"

cat > /etc/cron.d/suite-notarial <<EOF
# Suite Notarial: copias de seguridad (deploy/instalar-cron.sh). No editar a mano.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 3 * * * root /opt/suite-notarial/deploy/backup.sh >> $LOG 2>&1
30 4 * * 0 root /opt/suite-notarial/deploy/probar-restauracion.sh >> $LOG 2>&1
# Botón Supervielle: avisos recibidos durante la pausa entre consultas, y pagos cuyo aviso se perdió.
*/2 * * * * root flock -n /var/lock/suite-notarial-spv-avisos.lock timeout 100 $C exec -T api python -m app.modules.pagos.supervielle_cli procesar-avisos >> $LOG_SPV 2>&1
10 6,14 * * * root flock -n /var/lock/suite-notarial-spv-conciliar.lock timeout 1800 $C exec -T api python -m app.modules.pagos.supervielle_cli conciliar >> $LOG_SPV 2>&1
EOF
chmod 644 /etc/cron.d/suite-notarial

cat > /etc/logrotate.d/suite-notarial <<EOF
$LOG $LOG_SPV {
  monthly
  rotate 12
  compress
  missingok
  notifempty
}
EOF
touch "$LOG" "$LOG_SPV" && chmod 600 "$LOG" "$LOG_SPV"
echo "Programado: backup diario 3:15, prueba de restauración los domingos 4:30 (registro en $LOG)."
echo "Programado: Supervielle, avisos pendientes cada 2 minutos y conciliación 6:10 y 14:10 (registro en $LOG_SPV)."
