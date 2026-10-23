# Obsergent: the commands you run FROM THIS REPOSITORY, in one place.   `make help` lists them.
#
# The WSO2 gateway is a separate repository (github.com/wso2/api-platform): its commands (git clone, setup.sh,
# docker compose) are typed inside that repository, see the README ("Use it with the WSO2 API Platform MCP gateway").
# Nothing here touches it.
#
# Settings (ports, database file, gateway addresses) are in config.yaml.
#
# Python: uses the virtual environment that is already active; if none is, it uses ./.venv (create it with `make install`,
# which runs `uv venv` and `uv pip install -r requirements.txt`). No need to activate again. An active environment that no
# longer exists (e.g. activated before the folder was renamed) is ignored.
SHELL := /bin/bash

# ----------------------------------------------------------------------------------------------------------- settings
VENV_ACTIVE       := $(if $(VIRTUAL_ENV),$(wildcard $(VIRTUAL_ENV)/bin/python))
VENV_BIN          := $(if $(VENV_ACTIVE),$(VIRTUAL_ENV)/bin,.venv/bin)
# For `make proxy` / `make proxy-bg`: record any remote MCP server (default: the WSO2 gateway of config.yaml).
NAME              ?=
URL               ?=
PROXY_ARGS        := $(if $(NAME),--name $(NAME)) $(if $(URL),--url $(URL))

# Ports, addresses and the database file are NOT set here: they live in config.yaml (read by src/obsergent/config.py).
# `make config` prints what is in use.

.DEFAULT_GOAL := help

.PHONY: help
help:  ## show this list
	@echo "Obsergent: make <target>"; echo
	@awk 'BEGIN{FS=":.*## "} /^##@/{printf "\n%s\n", substr($$0,5)} /^[a-zA-Z0-9_-]+:.*## /{printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Install and build (once)
.PHONY: install ui-install ui-build env setup diagrams
# A virtual environment stores its absolute path (in bin/activate and every script's #! line), so after the folder is renamed
# or moved, .venv still exists but activating it points at the old folder: it is recreated. VS Code does not notice a
# recreated .venv by itself (new terminals stop activating it until its Python environments are refreshed), hence the hint.
install:  ## uv venv (if no environment is active or present; recreated if the folder was renamed) + uv pip install -r requirements.txt
	@if [ -d .venv ] && ! grep -qF "$(CURDIR)/.venv" .venv/bin/activate 2>/dev/null; then \
		echo ".venv was created in another folder (renamed or moved): recreating it"; rm -rf .venv; uv venv; \
		echo "VS Code: run 'Python Environments: Refresh All Environment Managers' (or 'Developer: Reload Window') so new terminals activate it"; \
	fi
	@if [ -z "$(VENV_ACTIVE)" ] && [ ! -d .venv ]; then uv venv; fi
	$(if $(VENV_ACTIVE),,VIRTUAL_ENV="$(CURDIR)/.venv") uv pip install -r requirements.txt
ui-install:  ## UI dependencies (needs Node.js 20+)
	cd ui && npm install
ui-build:  ## build the web UI into src/obsergent/server/static/
	cd ui && npm run build
diagrams:  ## redraw the diagrams in docs/diagrams/ (needs `make ui-install` once)
	cd ui && node scripts/make-diagrams.mjs
env:  ## create .env (language model settings) from .env.example if it does not exist
	test -f .env || cp .env.example .env
	@echo ".env is ready: edit the LLM_* lines to choose the model (Ollama by default)"
setup: install ui-install ui-build env  ## all of the above

##@ Run Obsergent
.PHONY: up up-grpc free-ports
# free-ports: stop whatever listens on the ports Obsergent is about to use (server.port, and server.grpc_port), for
# example a `make up` you started earlier. The ports come from config.yaml.
define kill_port
pids=$$(lsof -ti tcp:$(1) -sTCP:LISTEN 2>/dev/null); if [ -n "$$pids" ]; then echo "port $(1) is in use: stopping $$pids"; kill $$pids; sleep 1; fi
endef
free-ports:  ## stop whatever listens on Obsergent's server and gRPC ports (done automatically by up and up-grpc)
	@$(call kill_port,$$($(VENV_BIN)/obsergent config server.port))
	@$(call kill_port,$$($(VENV_BIN)/obsergent config server.grpc_port))
up:  ## the server + web UI at http://127.0.0.1:7318 (first stops anything already on that port)
	@$(call kill_port,$$($(VENV_BIN)/obsergent config server.port))
	$(VENV_BIN)/obsergent up
up-grpc:  ## same, plus the gRPC receiver on :4317 (first stops anything on either port)
	@$(MAKE) --no-print-directory free-ports
	$(VENV_BIN)/obsergent up --grpc

##@ Look at what was recorded (terminal; the web UI shows the same)
.PHONY: traces show sessions drift config prices prices-status usage price
traces:  ## list the recorded runs, newest first (LIMIT=N for more, default 20)
	$(VENV_BIN)/obsergent traces --limit $(or $(LIMIT),20)
show:  ## one run as a span tree: make show ID=<first characters of a run id from `make traces`>
	@test -n "$(ID)" || { echo "usage: make show ID=<run id or its first characters>  (ids are listed by: make traces)"; exit 1; }
	$(VENV_BIN)/obsergent show $(ID)
sessions:  ## list proxy sessions (one per proxy process, e.g. what Claude Desktop did)
	$(VENV_BIN)/obsergent sessions
drift:  ## MCP servers whose tool descriptions changed since first seen
	$(VENV_BIN)/obsergent drift
prices:  ## download the model price lists now (they also refresh by themselves while `make up` runs)
	$(VENV_BIN)/obsergent prices refresh
usage:  ## tokens used in the last 24 hours: totals, by model, heaviest questions, daily budget (HOURS=168 for a week)
	$(VENV_BIN)/obsergent usage --hours $(or $(HOURS),24)
price:  ## the price used for one model: make price MODEL=gpt-4o-mini [PROVIDER=openai]
	@test -n "$(MODEL)" || { echo "usage: make price MODEL=<model name> [PROVIDER=<provider>]"; exit 1; }
	$(VENV_BIN)/obsergent prices show $(MODEL) $(if $(PROVIDER),--provider $(PROVIDER))
prices-status:  ## when the price lists were last downloaded
	$(VENV_BIN)/obsergent prices status
config:  ## the settings in use (config.yaml + environment)
	$(VENV_BIN)/obsergent config

##@ With a WSO2 gateway (it must be running, see the README) or any remote MCP server
.PHONY: mcp-http register register-deny proxy traffic
mcp-http:  ## the Bookshop MCP server over HTTP on :9100 (the gateway in Docker reaches it as host.docker.internal)
	$(VENV_BIN)/python examples/bookshop/bookshop_http.py --host 0.0.0.0
register:  ## register it in the gateway (needs WSO2AP_GW_PASSWORD in the environment; safe to repeat)
	$(VENV_BIN)/python scripts/wso2_gateway.py register
register-deny:  ## same, plus the mcp-acl-list policy: only search_books is allowed
	$(VENV_BIN)/python scripts/wso2_gateway.py register --deny-price
proxy:  ## the recording proxy in front of the gateway (http://127.0.0.1:7319/mcp/wso2); other servers: NAME=x URL=https://…/mcp
	$(VENV_BIN)/obsergent proxy-http $(PROXY_ARGS)
traffic:  ## plain MCP test calls through the proxy (no agent, no model)
	$(VENV_BIN)/python scripts/wso2_gateway.py traffic

##@ Run everything in the background (one terminal is enough)
.PHONY: start stop status logs up-bg up-grpc-bg mcp-http-bg proxy-bg
RUN_DIR := .run
# spawn <name>,<command>: start it detached (nohup), log to .run/<name>.log, remember the pid in .run/<name>.pid
define spawn
mkdir -p $(RUN_DIR); if [ -f $(RUN_DIR)/$(1).pid ] && kill -0 $$(cat $(RUN_DIR)/$(1).pid) 2>/dev/null; then echo "$(1) is already running (pid $$(cat $(RUN_DIR)/$(1).pid))"; else nohup $(2) > $(RUN_DIR)/$(1).log 2>&1 & echo $$! > $(RUN_DIR)/$(1).pid; echo "started $(1)  (log: $(RUN_DIR)/$(1).log)"; fi
endef
# wait_for <name>,<url>: wait up to 30 seconds until the address answers
define wait_for
for i in $$(seq 30); do curl -s -o /dev/null $(2) && { echo "$(1) is up"; break; }; sleep 1; done
endef
up-bg: free-ports  ## the server + web UI, detached (log: .run/obsergent.log)
	@$(call spawn,obsergent,$(VENV_BIN)/obsergent up)
	@$(call wait_for,Obsergent,http://127.0.0.1:$$($(VENV_BIN)/obsergent config server.port)/health)
up-grpc-bg: free-ports  ## the server + web UI + gRPC receiver, detached (log: .run/obsergent.log)
	@$(call spawn,obsergent,$(VENV_BIN)/obsergent up --grpc)
	@$(call wait_for,Obsergent,http://127.0.0.1:$$($(VENV_BIN)/obsergent config server.port)/health)
mcp-http-bg:  ## the Bookshop MCP server over HTTP, detached (log: .run/mcp-http.log)
	@$(call kill_port,$$($(VENV_BIN)/obsergent config bookshop.http_port))
	@$(call spawn,mcp-http,$(VENV_BIN)/python examples/bookshop/bookshop_http.py --host 0.0.0.0)
	@$(call wait_for,MCP server,http://127.0.0.1:$$($(VENV_BIN)/obsergent config bookshop.http_port)/mcp)
proxy-bg:  ## Obsergent's recording proxy in front of the gateway, detached (log: .run/proxy.log)
	@$(call kill_port,$$($(VENV_BIN)/obsergent config proxy.port))
	@$(call spawn,proxy,$(VENV_BIN)/obsergent proxy-http $(PROXY_ARGS))
	@$(call wait_for,Proxy,http://127.0.0.1:$$($(VENV_BIN)/obsergent config proxy.port)/mcp/x)
start: up-grpc-bg mcp-http-bg  ## server+gRPC, MCP server, registration in the gateway, proxy: all detached (gateway: docker compose, see README)
	@if [ -n "$$WSO2AP_GW_PASSWORD" ]; then $(MAKE) --no-print-directory register; else echo "skipped register: export WSO2AP_GW_PASSWORD first, then run: make register"; fi
	@$(MAKE) --no-print-directory proxy-bg
status:  ## what runs in the background
	@for f in $(RUN_DIR)/*.pid; do [ -f "$$f" ] || continue; n=$$(basename $$f .pid); if kill -0 $$(cat $$f) 2>/dev/null; then echo "running  $$n (pid $$(cat $$f))"; else echo "stopped  $$n"; fi; done; ls $(RUN_DIR)/*.pid >/dev/null 2>&1 || echo "nothing started with make start"
logs:  ## follow the logs of everything started in the background (Ctrl+C stops following, not the programs)
	@tail -n 20 -F $(RUN_DIR)/*.log
stop:  ## stop everything started in the background (the WSO2 gateway is stopped with docker compose down in its folder)
	@for f in $(RUN_DIR)/*.pid; do [ -f "$$f" ] || continue; kill $$(cat $$f) 2>/dev/null && echo "stopped $$(basename $$f .pid)"; rm -f $$f; done; true
	@$(MAKE) --no-print-directory free-ports
	@$(call kill_port,$$($(VENV_BIN)/obsergent config proxy.port))
	@$(call kill_port,$$($(VENV_BIN)/obsergent config bookshop.http_port))

##@ Reset
.PHONY: reset-db clean
reset-db:  ## EMPTY Obsergent's database (config.yaml: storage.path); stop Obsergent first (make stop)
	db=$$($(VENV_BIN)/obsergent config storage.path); db=$${db/#\~/$$HOME}; rm -f "$$db" "$$db-wal" "$$db-shm"
	@echo "database emptied"
clean:  ## remove the built UI, caches and background logs (not the environment, not the database)
	rm -rf .pytest_cache .ruff_cache ui/node_modules/.vite src/obsergent/server/static/* $(RUN_DIR)
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
