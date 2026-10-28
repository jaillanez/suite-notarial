#!/usr/bin/env bash
# Completa en deploy/.env.server las contraseñas de la base y las claves internas que estén
# vacías. No muestra ningún valor y no toca las que ya tienen contenido (correr dos veces es
# inocuo). Las claves externas (SMTP, Mercado Pago, DeepSeek) se cargan aparte con `read -rs`.
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE=.env.server
[[ -f $ENV_FILE ]] || { cp .env.server.example "$ENV_FILE"; echo "Creado $ENV_FILE desde la plantilla."; }
chmod 600 "$ENV_FILE"

completar() {
  local clave="$1" valor="$2"
  if grep -qE "^${clave}=.+" "$ENV_FILE"; then
    echo "  $clave: ya tenía valor, sin cambios"
  else
    # Sin sed: el valor nunca pasa por la línea de comandos de otro proceso.
    python3 - "$ENV_FILE" "$clave" "$valor" <<'PY'
import sys
ruta, clave, valor = sys.argv[1:]
lineas = open(ruta).read().splitlines()
lineas = [f"{clave}={valor}" if l.startswith(f"{clave}=") else l for l in lineas]
if not any(l.startswith(f"{clave}=") for l in lineas):
    lineas.append(f"{clave}={valor}")
open(ruta, "w").write("\n".join(lineas) + "\n")
PY
    echo "  $clave: generada"
  fi
}

hex() { python3 -c "import secrets; print(secrets.token_hex($1))"; }
completar POSTGRES_SUPERUSER_PASSWORD "$(hex 24)"
completar SUITE_OWNER_PASSWORD "$(hex 24)"
completar SUITE_APP_PASSWORD "$(hex 24)"
completar JWT_SECRET "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
completar DATA_ENCRYPTION_KEY "$(python3 -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())')"
echo "Listo. Guardá una copia de $ENV_FILE fuera del servidor: sin DATA_ENCRYPTION_KEY no se"
echo "pueden leer los 2FA ya enrolados."
