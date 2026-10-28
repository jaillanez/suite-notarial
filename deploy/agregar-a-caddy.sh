#!/usr/bin/env bash
# Agrega el dominio de la Suite al Caddy compartido de suite-turnos, sin tocar los otros sitios.
#
# Uso (en el servidor, como root):  bash agregar-a-caddy.sh DOMINIO
#
# Parte de la configuración que el Caddy tiene EN EJECUCIÓN (puede ser más nueva que el archivo del
# disco si alguien lo editó con un método que reemplaza el archivo), guarda una copia, agrega solo
# el bloque de la Suite, lo valida y carga en caliente exactamente el archivo validado. Deja el
# archivo del disco igual a lo cargado, para que un reinicio del Caddy no pierda nada. Si la
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

# Una sola ejecución a la vez. El candado vive en un directorio solo de root (no en /var/lock,
# donde cualquiera podría dejar un enlace que redirija la escritura).
install -d -m 700 /run/agregar-a-caddy
exec 9>/run/agregar-a-caddy/lock
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
# El Caddyfile está montado en solo lectura dentro del contenedor: se carga en caliente la copia
# validada (la misma, sin volver a leerla) y se guarda esa versión en el disco, que es lo que el
# contenedor monta al reiniciarse.
docker exec "$CONT" caddy reload --config "$REMOTO" --adapter caddyfile >/dev/null 2>&1
cat "$NUEVO" > "$F"
if [[ "$(sha256sum < "$F" | cut -d" " -f1)" != "$HUELLA" ]]; then
  echo "El archivo del disco no quedó igual a lo validado: revisar $F (la copia está en $F.bak-$T-en-ejecucion)."
  exit 1
fi
echo "Listo: $DOMINIO agregado. Copia de la configuración anterior: $F.bak-$T-en-ejecucion"
echo "El contenedor del Caddy todavía monta una versión vieja del archivo: en un momento tranquilo,"
echo "'docker restart $CONT' (unos segundos sin los sitios) lo pone a leer el archivo actualizado."
