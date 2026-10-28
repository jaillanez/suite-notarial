#!/usr/bin/env bash
# Agrega el dominio de la Suite al Caddy compartido de suite-turnos, sin tocar los otros sitios.
#
# Uso (en el servidor, como root):
#   bash agregar-a-caddy.sh DOMINIO              agrega el dominio
#   bash agregar-a-caddy.sh --verificar          solo compara disco y ejecución; no cambia nada
#
# La autoridad es la configuración que el Caddy tiene EN EJECUCIÓN (se la pide a su API de
# administración). Antes de cambiar algo se verifica que el Caddyfile del disco produzca
# exactamente esa configuración; si difieren, no se toca nada (hay que reconciliar a mano). Recién
# entonces se agrega solo el bloque de la Suite, se valida, se carga en caliente el mismo archivo
# validado y se guarda en el disco. Si la validación falla, no cambia nada.
set -euo pipefail
umask 077
CONT=suite-turnos-caddy-1
F=/opt/suite-turnos/infra/caddy/Caddyfile
T=$(date +%Y%m%d-%H%M%S)

SOLO_VERIFICAR=0
DOMINIO=""
case "${1:-}" in
  --verificar) SOLO_VERIFICAR=1 ;;
  "") echo "Uso: bash agregar-a-caddy.sh DOMINIO | --verificar"; exit 1 ;;
  *) DOMINIO="$1" ;;
esac
if [[ $SOLO_VERIFICAR -eq 0 && ! "$DOMINIO" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then
  echo "Dominio inválido: $DOMINIO"
  exit 1
fi

# Una sola ejecución a la vez. El candado vive en un directorio solo de root (no en /var/lock,
# donde cualquiera podría dejar un enlace que redirija la escritura).
install -d -m 700 /run/agregar-a-caddy
exec 9>/run/agregar-a-caddy/lock
flock -n 9 || { echo "Otra ejecución está en curso."; exit 1; }

# Archivos de trabajo en un directorio privado (0700) que se borra al salir, y nombres únicos
# dentro del contenedor para esta ejecución.
TMPD=$(mktemp -d)
REMOTO="/tmp/Caddyfile.nuevo.$$-$T"
REMOTO_BASE="/tmp/Caddyfile.base.$$-$T"
trap 'rm -rf "$TMPD"; docker exec "$CONT" rm -f "$REMOTO" "$REMOTO_BASE" >/dev/null 2>&1 || true' EXIT
BASE="$TMPD/caddy-base"
NUEVO="$TMPD/caddy-nuevo"

normalizar() { python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), sort_keys=True))'; }

# 1. Lo que el Caddy tiene cargado ahora (JSON de su API de administración).
docker exec "$CONT" wget -qO- http://localhost:2019/config/ | normalizar > "$TMPD/en-ejecucion.json"

# 2. Lo que produce el Caddyfile del disco.
cat "$F" > "$BASE"
docker cp "$BASE" "$CONT":"$REMOTO_BASE"
docker exec "$CONT" caddy adapt --config "$REMOTO_BASE" --adapter caddyfile 2>/dev/null \
  | normalizar > "$TMPD/disco.json"

if ! cmp -s "$TMPD/en-ejecucion.json" "$TMPD/disco.json"; then
  echo "El Caddyfile del disco NO coincide con la configuración en ejecución: no se cambió nada."
  echo "Hay que reconciliarlos a mano antes de agregar dominios."
  exit 1
fi
if [[ $SOLO_VERIFICAR -eq 1 ]]; then
  echo "Coinciden: el Caddyfile del disco produce exactamente la configuración en ejecución."
  exit 0
fi

# Copias de respaldo: el Caddyfile y la configuración en ejecución (JSON).
install -m 600 "$BASE" "$F.bak-$T"
install -m 600 "$TMPD/en-ejecucion.json" "$F.bak-$T-en-ejecucion.json"
if grep -q "^$DOMINIO " "$BASE"; then
  echo "El dominio ya está en el Caddy: no hay nada que hacer."
  exit 0
fi

cp "$BASE" "$NUEVO"
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
# validada y se guarda esa versión en el disco, que es lo que el contenedor monta al reiniciarse.
docker exec "$CONT" caddy reload --config "$REMOTO" --adapter caddyfile >/dev/null 2>&1
# Se escribe sobre el mismo archivo (sin reemplazarlo) para que, tras un reinicio, el contenedor
# siga leyendo este archivo; si no quedó igual a lo validado, se restaura la copia.
cat "$NUEVO" > "$F"
if [[ "$(sha256sum < "$F" | cut -d" " -f1)" != "$HUELLA" ]]; then
  cat "$F.bak-$T" > "$F"
  echo "El archivo del disco no quedó igual a lo validado: se restauró la copia $F.bak-$T."
  echo "El Caddy ya tiene cargada la configuración nueva: revisar a mano."
  exit 1
fi
echo "Listo: $DOMINIO agregado. Copias: $F.bak-$T y $F.bak-$T-en-ejecucion.json"
echo "El contenedor del Caddy todavía monta una versión vieja del archivo: en un momento tranquilo,"
echo "'docker restart $CONT' (unos segundos sin los sitios) lo pone a leer el archivo actualizado."
