#!/usr/bin/env bash
# Agrega el dominio de la Suite al Caddy compartido de suite-turnos, sin tocar los otros sitios.
#
# Uso (en el servidor, como root):  bash agregar-a-caddy.sh DOMINIO
#
# Parte de la configuración que el Caddy tiene EN EJECUCIÓN (puede ser más nueva que el archivo del
# disco si alguien lo editó con un método que reemplaza el archivo), guarda una copia, agrega solo
# el bloque de la Suite, lo valida y aplica exactamente el archivo validado. Deja el archivo del
# disco igual al que está en ejecución, para que un reinicio del Caddy no pierda nada. Si la
# validación falla, no cambia nada.
set -euo pipefail
umask 077
DOMINIO="${1:?Uso: bash agregar-a-caddy.sh DOMINIO}"
if [[ ! "$DOMINIO" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then
  echo "Dominio inválido: $DOMINIO"
  exit 1
fi
CONT=suite-turnos-caddy-1
F=/opt/suite-turnos/infra/caddy/Caddyfile
T=$(date +%Y%m%d-%H%M%S)

# Una sola ejecución a la vez.
exec 9>/var/lock/agregar-a-caddy.lock
flock -n 9 || { echo "Otra ejecución está en curso."; exit 1; }

# Archivos de trabajo en un directorio privado (0700) que se borra al salir, y un nombre único
# dentro del contenedor para esta ejecución.
TMPD=$(mktemp -d)
REMOTO="/tmp/Caddyfile.nuevo.$$-$T"
trap 'rm -rf "$TMPD"; docker exec "$CONT" rm -f "$REMOTO" >/dev/null 2>&1 || true' EXIT
LIVE="$TMPD/caddy-live"
NUEVO="$TMPD/caddy-nuevo"

docker exec "$CONT" cat /etc/caddy/Caddyfile > "$LIVE"
install -m 600 "$LIVE" "$F.bak-$T-en-ejecucion"
if grep -q "^$DOMINIO " "$LIVE"; then
  echo "El dominio ya está en el Caddy: no hay nada que hacer."
  exit 0
fi

cp "$LIVE" "$NUEVO"
cat >> "$NUEVO" <<C

# Suite Notarial (Caja Notarial de San Juan) — proyecto aparte en /opt/suite-notarial.
$DOMINIO {
	encode zstd gzip
	reverse_proxy suite-notarial-web:80
}
C

# Se valida y se aplica la misma copia dentro del contenedor (lo validado es lo aplicado).
HUELLA=$(sha256sum < "$NUEVO" | cut -d" " -f1)
docker cp "$NUEVO" "$CONT":"$REMOTO"
if ! docker exec "$CONT" caddy validate --config "$REMOTO" --adapter caddyfile >/dev/null 2>&1; then
  echo "La configuración nueva no es válida: no se cambió nada."
  exit 1
fi
# Se escribe sobre el mismo archivo que usa el contenedor, sin reemplazarlo: un `mv` cambiaría el
# archivo y el contenedor seguiría leyendo el anterior (justamente lo que dejó al disco desfasado).
docker exec "$CONT" sh -c 'cat "$1" > /etc/caddy/Caddyfile' _ "$REMOTO"
docker exec "$CONT" cat /etc/caddy/Caddyfile > "$NUEVO"
if [[ "$(sha256sum < "$NUEVO" | cut -d" " -f1)" != "$HUELLA" ]]; then
  echo "Lo aplicado no coincide con lo validado: se vuelve a la copia anterior."
  docker exec -i "$CONT" sh -c 'cat > /etc/caddy/Caddyfile' < "$LIVE"
  exit 1
fi
cat "$NUEVO" > "$F"
docker exec "$CONT" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
echo "Listo: $DOMINIO agregado. Copia de la configuración anterior: $F.bak-$T-en-ejecucion"
