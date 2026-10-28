#!/usr/bin/env bash
# Agrega el dominio de la Suite al Caddy compartido de suite-turnos, sin tocar los otros sitios.
#
# Uso (en el servidor, como root):  bash agregar-a-caddy.sh DOMINIO
#
# Parte de la configuración que el Caddy tiene EN EJECUCIÓN (puede ser más nueva que el archivo del
# disco si alguien lo editó con un método que reemplaza el archivo), guarda una copia, agrega solo
# el bloque de la Suite, lo valida y recién entonces lo aplica. Deja el archivo del disco igual al
# que está en ejecución, para que un reinicio del Caddy no pierda nada. Si la validación falla, no
# cambia nada.
set -euo pipefail
DOMINIO="${1:?Uso: bash agregar-a-caddy.sh DOMINIO}"
CONT=suite-turnos-caddy-1
F=/opt/suite-turnos/infra/caddy/Caddyfile
T=$(date +%Y%m%d-%H%M)

docker exec "$CONT" cat /etc/caddy/Caddyfile > /tmp/caddy-live
cp /tmp/caddy-live "$F.bak-$T-en-ejecucion"
if grep -q "^$DOMINIO " /tmp/caddy-live; then
  echo "El dominio ya está en el Caddy: no hay nada que hacer."
  exit 0
fi

cp /tmp/caddy-live /tmp/caddy-nuevo
cat >> /tmp/caddy-nuevo <<C

# Suite Notarial (Caja Notarial de San Juan) — proyecto aparte en /opt/suite-notarial.
$DOMINIO {
	encode zstd gzip
	reverse_proxy suite-notarial-web:80
}
C

docker cp /tmp/caddy-nuevo "$CONT":/tmp/Caddyfile.nuevo
if ! docker exec "$CONT" caddy validate --config /tmp/Caddyfile.nuevo --adapter caddyfile \
  > /tmp/caddy-validacion.log 2>&1; then
  echo "La configuración nueva no es válida: no se cambió nada."
  tail -5 /tmp/caddy-validacion.log
  exit 1
fi

# Se escribe sobre el mismo archivo que usa el contenedor (no se reemplaza) y en el disco.
docker exec -i "$CONT" sh -c 'cat > /etc/caddy/Caddyfile' < /tmp/caddy-nuevo
cat /tmp/caddy-nuevo > "$F"
docker exec "$CONT" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
echo "Listo: $DOMINIO agregado. Copia de la configuración anterior: $F.bak-$T-en-ejecucion"
