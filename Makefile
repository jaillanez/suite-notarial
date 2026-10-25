SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv
PY := $(VENV)/bin/python
PYTHON ?= python3

# Librerías nativas de Homebrew (libmagic, pango) para python-magic y weasyprint.
export DYLD_FALLBACK_LIBRARY_PATH ?= /opt/homebrew/lib
# Puertos de desarrollo; sobreescribir si chocan con otro proyecto: make dev API_PORT=8010 WEB_PORT=5183
export API_PORT ?= 8000
export WEB_PORT ?= 5173

.PHONY: help install install-backend install-frontend db mailpit backend frontend dev \
        migrate revision test test-backend test-frontend lint lint-backend lint-frontend fmt hooks

help: ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend hooks ## Instala dependencias de backend, frontend y pre-commit

install-backend: ## Crea el venv e instala el backend con extras de desarrollo
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -e "$(BACKEND)[dev]"
	test -f $(BACKEND)/.env || cp $(BACKEND)/.env.example $(BACKEND)/.env

install-frontend: ## Instala dependencias del frontend
	cd $(FRONTEND) && npm ci

db: ## Crea rol y bases locales (idempotente)
	./scripts/bootstrap_db.sh

mailpit: ## Levanta Mailpit (SMTP :1025, UI :8025)
	mailpit --smtp 127.0.0.1:1025 --listen 127.0.0.1:8025

backend: ## Levanta la API con recarga en :$(API_PORT)
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port $(API_PORT)

frontend: ## Levanta Vite en :$(WEB_PORT)
	cd $(FRONTEND) && npm run dev -- --host 127.0.0.1

dev: ## Levanta Mailpit + backend + frontend juntos
	./scripts/dev.sh

migrate: ## Aplica migraciones pendientes
	cd $(BACKEND) && .venv/bin/alembic upgrade head

revision: ## Genera una migración: make revision m="descripcion"
	@test -n "$(m)" || (echo 'Uso: make revision m="descripcion"' && exit 1)
	cd $(BACKEND) && .venv/bin/alembic revision --autogenerate -m "$(m)"

test: test-backend test-frontend ## Corre todos los tests

test-backend:
	cd $(BACKEND) && .venv/bin/pytest

test-frontend:
	cd $(FRONTEND) && npm test

lint: lint-backend lint-frontend ## Linters y chequeo de tipos

lint-backend:
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app tests

lint-frontend:
	cd $(FRONTEND) && npm run lint && npm run format:check && npm run typecheck

fmt: ## Formatea backend y frontend
	cd $(BACKEND) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd $(FRONTEND) && npm run format

hooks: ## Instala los hooks de pre-commit
	pre-commit install
