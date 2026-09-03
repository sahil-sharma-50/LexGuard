# Lexguard local development (Docker-first)
#
# Quick start:
#   make setup          # copy .env.example
#   make up             # build and start the full stack
#   make preflight      # verify readiness inside the api container

SHELL := /bin/bash
.DEFAULT_GOAL := help

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
COMPOSE := docker compose -f "$(REPO_ROOT)/docker-compose.yml"
ENV_FILE := $(REPO_ROOT)/.env

.PHONY: help setup env up down restart logs ps build migrate seed preflight \
        verify dev stop shell-api shell-scheduler native-setup native-dev native-stop

help:
	@echo "Lexguard: Docker local development"
	@echo ""
	@echo "Docker (recommended):"
	@echo "  make setup        Copy .env.example -> .env if missing"
	@echo "  make up           Build images and start postgres, mcp, api, scheduler, web"
	@echo "  make down         Stop and remove containers"
	@echo "  make restart      Restart the stack"
	@echo "  make logs         Follow service logs"
	@echo "  make ps           Show container status"
	@echo "  make migrate      Run database migrations"
	@echo "  make seed         Seed risk state + forecast artifacts"
	@echo "  make preflight    Run readiness checks in the api container"
	@echo "  make shell-api    Open a shell in the api container"
	@echo ""
	@echo "Native (optional, requires uv + pnpm + Postgres):"
	@echo "  make native-setup Install local Python + web dependencies"
	@echo "  make native-dev   Run services without Docker"
	@echo "  make native-stop  Stop native background services"
	@echo ""
	@echo "Quality:"
	@echo "  make verify       Offline lint, types, tests, and web build"

env:
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp "$(REPO_ROOT)/.env.example" "$(ENV_FILE)"; \
		echo "Created $(ENV_FILE). Fill in Alpaca paper keys + OpenAI key"; \
	else \
		echo "$(ENV_FILE) already exists (not overwritten)"; \
	fi

setup: env
	@echo ""
	@echo "Setup complete."
	@echo "  1. Edit $(ENV_FILE) with your API keys"
	@echo "  2. make up"
	@echo "  3. make preflight"
	@echo "  4. Open http://localhost:3000"

require-env:
	@test -f "$(ENV_FILE)" || { echo "Missing $(ENV_FILE). Run 'make setup'"; exit 1; }

require-docker:
	@command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/get-docker/"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required"; exit 1; }

up: require-env require-docker
	@$(COMPOSE) up --build -d
	@echo ""
	@echo "Stack starting:"
	@echo "  Web UI  http://localhost:3000"
	@echo "  API     http://localhost:8000"
	@echo "  MCP     http://localhost:8010/mcp"
	@echo ""
	@echo "Run 'make logs' to follow startup, then 'make preflight'."

down: require-docker
	@$(COMPOSE) down

restart: require-docker
	@$(COMPOSE) restart

logs: require-docker
	@$(COMPOSE) logs -f --tail=100

ps: require-docker
	@$(COMPOSE) ps

build: require-env require-docker
	@$(COMPOSE) build

migrate: require-env require-docker
	@$(COMPOSE) run --rm migrate

seed: require-env require-docker
	@$(COMPOSE) run --rm --no-deps --entrypoint /bin/sh api -c '\
		lexguard seed-risk-state && \
		lexguard seed-forecast --symbol SPY --output /app/agent/artifacts/generated/forecast-SPY.json && \
		lexguard seed-forecast --symbol QQQ --output /app/agent/artifacts/generated/forecast-QQQ.json && \
		lexguard seed-forecast --symbol IWM --output /app/agent/artifacts/generated/forecast-IWM.json'

preflight: require-env require-docker
	@$(COMPOSE) run --rm --no-deps api run-preflight

shell-api: require-docker
	@$(COMPOSE) run --rm --entrypoint /bin/sh api

dev: up

stop: down

verify:
	@bash "$(REPO_ROOT)/scripts/verify.sh"

native-setup:
	@$(MAKE) -f "$(REPO_ROOT)/Makefile.native" setup

native-dev:
	@$(MAKE) -f "$(REPO_ROOT)/Makefile.native" dev

native-stop:
	@$(MAKE) -f "$(REPO_ROOT)/Makefile.native" stop
