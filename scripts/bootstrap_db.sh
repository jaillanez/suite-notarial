#!/usr/bin/env bash
# Crea los roles y las bases locales (idempotente). Requiere un usuario de PostgreSQL con
# permiso para crear roles y bases (el superusuario local en desarrollo, `postgres` en CI).
#
# Dos roles separados (mínimo privilegio):
#   suite_owner  dueño del esquema; solo lo usan las migraciones (MIGRATIONS_DATABASE_URL).
#   suite_app    rol de la aplicación en ejecución (DATABASE_URL); no es dueño de ninguna
#                tabla, así que no puede alterar el esquema ni desactivar triggers.
set -euo pipefail

DB="${DB_NAME:-suite_notarial}"
DB_TEST="${DB_TEST_NAME:-suite_notarial_test}"
# Base descartable para ensayar el corte y la reversa (make ensayo-corte).
DB_ENSAYO="${DB_ENSAYO_NAME:-suite_notarial_ensayo}"
OWNER="${DB_OWNER_ROLE:-suite_owner}"
OWNER_PASS="${DB_OWNER_PASS:-suite_owner_dev}" # solo desarrollo; prod va por secreto
APP="${DB_ROLE:-suite_app}"
APP_PASS="${DB_PASS:-suite_app_dev}" # solo desarrollo; prod va por secreto

ensure_role() {
  local role="$1" pass="$2"
  psql -v ON_ERROR_STOP=1 -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='$role'" | grep -q 1 ||
    psql -v ON_ERROR_STOP=1 -d postgres -c \
      "CREATE ROLE $role LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '$pass';"
}

ensure_role "$OWNER" "$OWNER_PASS"
ensure_role "$APP" "$APP_PASS"

for name in "$DB" "$DB_TEST" "$DB_ENSAYO"; do
  psql -v ON_ERROR_STOP=1 -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$name'" | grep -q 1 ||
    psql -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE $name OWNER $OWNER;"

  current_owner="$(psql -v ON_ERROR_STOP=1 -d postgres -tAc \
    "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$name'")"
  if [[ "$current_owner" != "$OWNER" ]]; then
    echo "ERROR: la base $name pertenece a '$current_owner', no a '$OWNER'." >&2
    echo "       Es una base de una versión anterior: borrala (DROP DATABASE $name) y reintentá." >&2
    exit 1
  fi

  psql -v ON_ERROR_STOP=1 -d "$name" <<SQL
-- pgcrypto habilita gen_random_uuid() para las PK UUID v4.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER SCHEMA public OWNER TO $OWNER;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO $APP;
GRANT CONNECT ON DATABASE $name TO $APP;
-- Lo que cree el dueño queda disponible para la app con permisos DML, nunca DDL.
ALTER DEFAULT PRIVILEGES FOR ROLE $OWNER IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $APP;
ALTER DEFAULT PRIVILEGES FOR ROLE $OWNER IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO $APP;
SQL
done

echo "OK: bases $DB, $DB_TEST y $DB_ENSAYO listas (dueño $OWNER, aplicación $APP)."
