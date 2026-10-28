#!/usr/bin/env bash
# Deploy de la Suite Notarial en el servidor: git pull -> build -> migraciones -> levantar.
# Las migraciones corren en el servicio `migrate` antes de la API; si fallan, la API vieja
# sigue andando. No borra volúmenes ni datos.
set -euo pipefail
cd /opt/suite-notarial
COMPOSE="docker compose --env-file deploy/.env.server -f deploy/compose.server.yml"

[[ -f deploy/.env.server ]] || { echo "Falta deploy/.env.server (ver deploy/README.md)."; exit 1; }
valor() { grep -E "^$1=" deploy/.env.server | tail -1 | cut -d= -f2- || true; }
EDGE=$(valor EDGE_NETWORK); EDGE=${EDGE:-suite-turnos_edge}
PUERTO=$(valor WEB_BIND_PORT); PUERTO=${PUERTO:-8686}
if grep -q "DOMINIO-A-DEFINIR" deploy/.env.server; then
  echo "Falta definir el dominio en deploy/.env.server (PUBLIC_WEB_URL y CORS_ORIGINS)."; exit 1
fi
EDGE_SUBNET=$(docker network inspect "$EDGE" -f '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null) \
  || { echo "No existe la red del Caddy compartido ($EDGE)."; exit 1; }
export EDGE_SUBNET
# Se guarda en .env.server para que los comandos manuales (seed-dev, create-admin) también lo tengan.
if grep -q "^EDGE_SUBNET=" deploy/.env.server; then
  sed -i "s|^EDGE_SUBNET=.*|EDGE_SUBNET=$EDGE_SUBNET|" deploy/.env.server
else
  echo "EDGE_SUBNET=$EDGE_SUBNET" >> deploy/.env.server
fi

echo "== 1/5  git pull =="
git pull --ff-only

echo "== 2/5  build =="
$COMPOSE build migrate web

echo "== 3/5  migraciones =="
$COMPOSE up -d postgres
$COMPOSE run --rm migrate

echo "== 4/5  levantar api y web =="
$COMPOSE up -d --no-deps --wait api
$COMPOSE up -d --no-deps web

echo "== 5/5  estado =="
$COMPOSE ps
curl -s -o /dev/null -w "web local: %{http_code}\n" "http://127.0.0.1:$PUERTO/" || true
curl -s "http://127.0.0.1:$PUERTO/api/health" || true; echo
