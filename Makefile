# AgentTrace: the commands you run FROM THIS REPOSITORY, in one place.   `make help` lists them.
#
# The WSO2 gateway is a separate repository (github.com/wso2/api-platform): its commands (git clone, setup.sh,
# docker compose) are typed inside that repository, see README section 4. Nothing here touches it.
#
# Settings (ports, database file, gateway addresses) are in config.yaml.
#
# Python: uses the virtual environment that is already active; if none is, it uses ./.venv (create it with `make install`,
# which runs `uv venv` and `uv pip install -e ".[...]"`). No need to activate again.
SHELL := /bin/bash

# ----------------------------------------------------------------------------------------------------------- settings
VENV_BIN          := $(if $(VIRTUAL_ENV),$(VIRTUAL_ENV)/bin,.venv/bin)
EXTRAS            ?= dev,langchain,examples,grpc

# Ports, addresses and the database file are NOT set here: they live in config.yaml (read by src/agenttrace/config.py).
# `agenttrace config` prints what is in use, e.g. `agenttrace config server.port`.

.DEFAULT_GOAL := help

.PHONY: help
help:  ## show this list
	@echo "AgentTrace: make <target>"; echo
	@awk 'BEGIN{FS=":.*## "} /^##@/{printf "\n%s\n", substr($$0,5)} /^[a-zA-Z0-9_-]+:.*## /{printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Install and build (once)
.PHONY: install ui-install ui-build env setup
install:  ## uv venv (if no environment is active or present) + uv pip install -e ".[EXTRAS]"
	@if [ -z "$$VIRTUAL_ENV" ] && [ ! -d .venv ]; then uv venv; fi
	uv pip install -e ".[$(EXTRAS)]"
ui-install:  ## UI dependencies (needs Node.js 20+)
	cd ui && npm install
ui-build:  ## build the web UI into src/agenttrace/server/static/
	cd ui && npm run build
env:  ## create .env (language model settings) from .env.example if it does not exist
	test -f .env || cp .env.example .env
	@echo ".env is ready: edit the LLM_* lines to choose the model (Ollama by default)"
setup: install ui-install ui-build env  ## all of the above

##@ Run AgentTrace
.PHONY: up up-grpc free-ports
# free-ports: stop whatever listens on the ports AgentTrace is about to use (server.port, and server.grpc_port), for
# example an `agenttrace up` you started earlier. The ports come from config.yaml.
define kill_port
pids=$$(lsof -ti tcp:$(1) -sTCP:LISTEN 2>/dev/null); if [ -n "$$pids" ]; then echo "port $(1) is in use: stopping $$pids"; kill $$pids; sleep 1; fi
endef
free-ports:  ## stop whatever listens on AgentTrace's server and gRPC ports (done automatically by up and up-grpc)
	@$(call kill_port,$$($(VENV_BIN)/agenttrace config server.port))
	@$(call kill_port,$$($(VENV_BIN)/agenttrace config server.grpc_port))
up:  ## the server + web UI at http://127.0.0.1:7318 (first stops anything already on that port)
	@$(call kill_port,$$($(VENV_BIN)/agenttrace config server.port))
	$(VENV_BIN)/agenttrace up
up-grpc:  ## same, plus the gRPC receiver on :4317 (first stops anything on either port)
	@$(MAKE) --no-print-directory free-ports
	$(VENV_BIN)/agenttrace up --grpc

##@ Look at what was recorded (terminal; the web UI shows the same)
.PHONY: traces show sessions drift config
traces:  ## list the recorded runs, newest first (LIMIT=N for more, default 20)
	$(VENV_BIN)/agenttrace traces --limit $(or $(LIMIT),20)
show:  ## one run as a span tree: make show ID=<first characters of a run id from `make traces`>
	@test -n "$(ID)" || { echo "usage: make show ID=<run id or its first characters>  (ids are listed by: make traces)"; exit 1; }
	$(VENV_BIN)/agenttrace show $(ID)
sessions:  ## list proxy sessions (one per proxy process, e.g. what Claude Desktop did)
	$(VENV_BIN)/agenttrace sessions
drift:  ## MCP servers whose tool descriptions changed since first seen
	$(VENV_BIN)/agenttrace drift
config:  ## the settings in use (config.yaml + environment)
	$(VENV_BIN)/agenttrace config

##@ With a WSO2 gateway (it must be running: README section 4)
.PHONY: mcp-http register register-deny proxy traffic
mcp-http:  ## the Bookshop MCP server over HTTP on :9100 (the gateway in Docker reaches it as host.docker.internal)
	$(VENV_BIN)/python examples/bookshop/bookshop_http.py --host 0.0.0.0
register:  ## register it in the gateway (needs WSO2AP_GW_PASSWORD in the environment; safe to repeat)
	$(VENV_BIN)/python scripts/wso2_gateway.py register
register-deny:  ## same, plus the mcp-acl-list policy: only search_books is allowed
	$(VENV_BIN)/python scripts/wso2_gateway.py register --deny-price
proxy:  ## AgentTrace's recording proxy in front of the gateway (clients use http://127.0.0.1:7319/mcp/wso2)
	$(VENV_BIN)/agenttrace proxy-http
traffic:  ## plain MCP test calls through the proxy (no agent, no model)
	$(VENV_BIN)/python scripts/wso2_gateway.py traffic

##@ Reset
.PHONY: reset-db clean
reset-db:  ## EMPTY AgentTrace's database (config.yaml: storage.path); stop `agenttrace up` first
	db=$$($(VENV_BIN)/agenttrace config storage.path); db=$${db/#\~/$$HOME}; rm -f "$$db" "$$db-wal" "$$db-shm"
	@echo "database emptied"
clean:  ## remove the built UI and caches (not the environment, not the database)
	rm -rf .pytest_cache .ruff_cache ui/node_modules/.vite src/agenttrace/server/static/*
	find . -name __pycache__ -not -path "./.venv/*" -not -path "./ui/node_modules/*" -prune -exec rm -rf {} +

##@ Checks
.PHONY: lint test test-ui test-e2e check
lint:  ## ruff over the Python code
	$(VENV_BIN)/ruff check src tests examples scripts
test:  ## backend tests (the agent test needs Ollama and is skipped without it)
	$(VENV_BIN)/pytest -q
test-ui:  ## UI type check, unit tests and production build
	cd ui && npm run typecheck && npm test && npm run build
test-e2e:  ## browser tests (installs Chromium the first time)
	cd ui && npx playwright install chromium && npx playwright test
check: lint test test-ui  ## lint + backend + UI tests
