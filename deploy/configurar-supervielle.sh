#!/usr/bin/env bash
# Carga en deploy/.env.server las credenciales del botón de pagos Supervielle, reinicia la API y
# prueba el acceso al banco. Los secretos se escriben sin mostrarse ni quedar en el historial.
# Se puede repetir (por ejemplo, al pasar de pruebas a producción): reemplaza los valores.
#   cd /opt/suite-notarial && ./deploy/configurar-supervielle.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=deploy/.env.server
C="docker compose --env-file $ENV_FILE -f deploy/compose.server.yml"
[[ -f $ENV_FILE ]] || { echo "Falta $ENV_FILE."; exit 1; }

# Reemplaza (o agrega) CLAVE=valor sin pasar el valor por la línea de comandos.
guardar() {
  local clave=$1 valor=$2 tmp
  tmp=$(mktemp "$ENV_FILE.XXXXXX")
  CLAVE="$clave" VALOR="$valor" awk '
    BEGIN { c = ENVIRON["CLAVE"]; v = ENVIRON["VALOR"]; hecho = 0 }
    index($0, c "=") == 1 { print c "=" v; hecho = 1; next }
    { print }
    END { if (!hecho) print c "=" v }
  ' "$ENV_FILE" > "$tmp"
  chmod 600 "$tmp" && mv "$tmp" "$ENV_FILE"
}

preguntar() {  # preguntar CLAVE "texto" [secreto]
  local valor
  if [[ ${3:-} == secreto ]]; then
    read -r -s -p "$2: " valor; echo
  else
    read -r -p "$2: " valor
  fi
  [[ -n $valor ]] || { echo "  (sin cambios)"; return; }
  guardar "$1" "$valor"
}

echo "Botón de pagos Supervielle. Enter deja el valor actual."
read -r -p "Ambiente del banco [pruebas/produccion]: " ambiente
case $ambiente in
  produccion)
    echo "Direcciones de producción (las confirma el banco):"
    preguntar SUPERVIELLE_API_URL "URL de la API (…/banca-comercial/recaudaciones)"
    preguntar SUPERVIELLE_AUTH_URL "URL del token"
    preguntar SUPERVIELLE_FORWARDED_HOST "X-Forwarded-Host"
    ;;
  pruebas)
    # Sin estas variables rigen las del ambiente de pruebas (valores por defecto de la Suite).
    for clave in SUPERVIELLE_API_URL SUPERVIELLE_AUTH_URL SUPERVIELLE_FORWARDED_HOST; do
      sed -i "/^$clave=/d" "$ENV_FILE"
    done
    ;;
  *) echo "Escribí pruebas o produccion."; exit 1 ;;
esac
preguntar SUPERVIELLE_CONVENIO "Número de convenio"
preguntar SUPERVIELLE_USUARIO "Usuario (username)"
preguntar SUPERVIELLE_CLAVE "Clave (password)" secreto
preguntar SUPERVIELLE_CLIENT_ID "client_id"
preguntar SUPERVIELLE_CLIENT_SECRET "client_secret" secreto
preguntar SUPERVIELLE_IBM_CLIENT_ID "x-ibm-client-id" secreto

echo "Reiniciando la API con la configuración nueva…"
$C up -d --no-deps --force-recreate api >/dev/null
for _ in $(seq 1 30); do
  $C exec -T api python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health')" \
    >/dev/null 2>&1 && break
  sleep 2
done
$C exec -T api python -m app.modules.pagos.supervielle_cli probar || {
  echo "El banco no aceptó el acceso: revisá los valores y volvé a correr este script."; exit 1; }

web=$(awk -F= '$1 == "PUBLIC_WEB_URL" { print $2 }' "$ENV_FILE" | sed 's:/*$::')
echo
echo "Listo. Dirección de aviso de pagos para registrar en el banco:"
echo "  $web/api/v1/pagos/supervielle/aviso/{{hash}}"
