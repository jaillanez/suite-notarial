#!/usr/bin/env bash
# Completa en deploy/.env.server las contraseñas de la base y las claves internas que estén
# vacías. No muestra ningún valor y no toca las que ya tienen contenido (correr dos veces es
# inocuo). Las claves se generan y escriben dentro del mismo proceso: nunca pasan por la línea
# de comandos. Las externas (SMTP, Mercado Pago, DeepSeek) se cargan aparte con `read -rs`.
set -euo pipefail
umask 077
cd "$(dirname "$0")"
ENV_FILE=.env.server
[[ -f $ENV_FILE ]] || { install -m 600 .env.server.example "$ENV_FILE"; echo "Creado $ENV_FILE desde la plantilla."; }
chmod 600 "$ENV_FILE"

python3 - "$ENV_FILE" <<'PY'
import base64, os, secrets, sys, tempfile

ruta = sys.argv[1]
generadores = {
    "POSTGRES_SUPERUSER_PASSWORD": lambda: secrets.token_hex(24),
    "SUITE_OWNER_PASSWORD": lambda: secrets.token_hex(24),
    "SUITE_APP_PASSWORD": lambda: secrets.token_hex(24),
    "JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "DATA_ENCRYPTION_KEY": lambda: base64.b64encode(os.urandom(32)).decode(),
}
with open(ruta) as f:
    lineas = f.read().splitlines()
for clave, generar in generadores.items():
    actual = [i for i, l in enumerate(lineas) if l.startswith(f"{clave}=")]
    if actual and lineas[actual[-1]] != f"{clave}=":
        print(f"  {clave}: ya tenía valor, sin cambios")
        continue
    nueva = f"{clave}={generar()}"
    if actual:
        lineas[actual[-1]] = nueva
    else:
        lineas.append(nueva)
    print(f"  {clave}: generada")
# Escritura atómica con permisos 600.
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(ruta)), prefix=".env.")
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lineas) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, ruta)
PY
echo "Listo. Guardá una copia de $ENV_FILE fuera del servidor: sin DATA_ENCRYPTION_KEY no se"
echo "pueden leer los 2FA ya enrolados."
