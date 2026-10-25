#!/usr/bin/env bash
# Crea el rol y la base de datos local de desarrollo (idempotente).
set -euo pipefail

DB="${DB_NAME:-suite_notarial}"
DB_TEST="${DB_TEST_NAME:-suite_notarial_test}"
ROLE="${DB_ROLE:-suite_app}"
PASS="${DB_PASS:-suite_app_dev}" # solo desarrollo; prod va por env/secreto

psql -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'" | grep -q 1 ||
  psql -d postgres -c "CREATE ROLE $ROLE LOGIN PASSWORD '$PASS';"

for name in "$DB" "$DB_TEST"; do
  psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$name'" | grep -q 1 ||
    psql -d postgres -c "CREATE DATABASE $name OWNER $ROLE;"
  # pgcrypto habilita gen_random_uuid() para las PK UUID v4.
  psql -d "$name" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
done

echo "OK: bases $DB y $DB_TEST listas."
