#!/usr/bin/env bash
# Verifica que backend/requirements*.lock correspondan a backend/pyproject.toml: los regenera en
# una carpeta aparte (respetando las versiones ya fijadas) y compara. No toca los originales.
set -euo pipefail
cd "$(dirname "$0")/../backend"

compilar() {
  uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes \
    --no-header -q "$@"
}

aparte="$(mktemp -d)"
trap 'rm -r -- "$aparte"' EXIT
cp requirements.lock requirements-dev.lock "$aparte/"
compilar -o "$aparte/requirements.lock"
compilar --extra dev -o "$aparte/requirements-dev.lock"

if diff -u requirements.lock "$aparte/requirements.lock" \
  && diff -u requirements-dev.lock "$aparte/requirements-dev.lock"; then
  echo "OK: los .lock corresponden a pyproject.toml."
else
  echo "Los .lock no corresponden a pyproject.toml: corré make lock." >&2
  exit 1
fi
