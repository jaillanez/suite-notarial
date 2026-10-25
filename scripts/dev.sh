#!/usr/bin/env bash
# Levanta Mailpit, backend y frontend juntos; Ctrl+C detiene todo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Las librerías nativas de Homebrew (libmagic, pango) no están en la ruta por defecto del linker.
export DYLD_FALLBACK_LIBRARY_PATH="${DYLD_FALLBACK_LIBRARY_PATH:-/opt/homebrew/lib}"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
export API_PORT WEB_PORT

pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

prefix() { sed -u "s/^/[$1] /"; }

if command -v mailpit >/dev/null; then
  (mailpit --smtp 127.0.0.1:1025 --listen 127.0.0.1:8025 2>&1 | prefix mail) &
  pids+=($!)
else
  echo "[dev] mailpit no está instalado (brew install mailpit); se omite." >&2
fi

(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT" 2>&1 | prefix api) &
pids+=($!)

(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 2>&1 | prefix web) &
pids+=($!)

echo "[dev] API http://localhost:$API_PORT/api/health · Web http://localhost:$WEB_PORT · Mailpit http://localhost:8025"
wait
