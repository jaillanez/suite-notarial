#!/usr/bin/env bash
# Primer arranque de la base (lo ejecuta la imagen de PostgreSQL una sola vez, con el volumen
# vacío). Mismo esquema de roles que scripts/bootstrap_db.sh, con contraseñas del .env.server:
#   suite_owner  dueño del esquema; solo lo usan las migraciones.
#   suite_app    rol de la aplicación; solo DML, no puede alterar tablas ni desactivar triggers.
set -euo pipefail
: "${SUITE_DB:?}" "${SUITE_OWNER_PASSWORD:?}" "${SUITE_APP_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pass="$SUITE_OWNER_PASSWORD" -v app_pass="$SUITE_APP_PASSWORD" <<'SQL'
CREATE ROLE suite_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'owner_pass';
CREATE ROLE suite_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_pass';
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -c "CREATE DATABASE \"$SUITE_DB\" OWNER suite_owner;"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$SUITE_DB" <<SQL
-- pgcrypto habilita gen_random_uuid() para las PK UUID v4.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER SCHEMA public OWNER TO suite_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO suite_app;
REVOKE CONNECT ON DATABASE "$SUITE_DB" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$SUITE_DB" TO suite_owner, suite_app;
ALTER DEFAULT PRIVILEGES FOR ROLE suite_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO suite_app;
ALTER DEFAULT PRIVILEGES FOR ROLE suite_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO suite_app;
SQL
echo "OK: base $SUITE_DB lista (dueño suite_owner, aplicación suite_app)."
