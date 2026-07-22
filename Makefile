# Dentro AI Factory — Makefile

LABEL := com.dentroio.factory-agent
LOG_DIR := $(HOME)/Library/Logs/factory-agent

.PHONY: help \
        agent-setup \
        up down logs restart \
        agent-install agent-remove agent-start agent-stop agent-logs agent-status agent-once \
        docs-check docs-check-strict docs-gdrive \
        oryntra-open

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

agent-setup:  ## First-time setup — stores secrets in macOS Keychain
	@bash scripts/agent-setup.sh

# ── Docker Compose (dashboard + orchestrator + watchdog) ─────────────────────

up:  ## Start factory services (reads secrets from macOS Keychain if available)
	@bash scripts/factory-env.sh > .env.runtime 2>/dev/null || true
	@if [ -s .env.runtime ]; then \
		docker compose -f docker-compose.status.yml --env-file .env.runtime up -d; \
	else \
		docker compose -f docker-compose.status.yml up -d; \
	fi
	@rm -f .env.runtime
	@echo "Dashboard: http://localhost:8099   Orchestrator: http://localhost:8100 (localhost only)"

vault-export-keys:  ## Save Vault unseal key + root token from Docker volume to macOS Keychain
	@echo "Reading Vault keys from Docker volume..."
	@UNSEAL_KEY=$$(docker run --rm -v agentic-factory_vault-keys:/vault/keys:ro alpine cat /vault/keys/unseal_key 2>/dev/null) && \
	ROOT_TOKEN=$$(docker run --rm -v agentic-factory_vault-keys:/vault/keys:ro alpine cat /vault/keys/root_token 2>/dev/null) && \
	security delete-generic-password -s "dentroio-factory" -a "VAULT_UNSEAL_KEY" 2>/dev/null || true && \
	security add-generic-password -s "dentroio-factory" -a "VAULT_UNSEAL_KEY" -w "$$UNSEAL_KEY" && \
	security delete-generic-password -s "dentroio-factory" -a "VAULT_ROOT_TOKEN" 2>/dev/null || true && \
	security add-generic-password -s "dentroio-factory" -a "VAULT_ROOT_TOKEN" -w "$$ROOT_TOKEN" && \
	echo "  Vault unseal key and root token saved to Keychain under 'dentroio-factory'." || \
	echo "  ERROR: Could not read from vault-keys volume. Is the factory running? (make up)"

down:  ## Stop all factory services
	docker compose -f docker-compose.status.yml down

logs:  ## Tail logs for all factory services
	docker compose -f docker-compose.status.yml logs -f

restart:  ## Rebuild and restart all factory services
	docker compose -f docker-compose.status.yml build
	docker compose -f docker-compose.status.yml up -d --force-recreate

pin-base-images:  ## Pre-pull Docker base images used by Clarion builds (run daily to avoid DeadlineExceeded)
	docker pull node:20-alpine
	docker pull nginx:alpine
	docker pull python:3.12-slim

# ── Agent runner daemon (runs Claude on your Mac, not in Docker) ──────────────

agent-install:  ## Install agent daemon + start it (run once after filling in .env)
	@bash scripts/agent-install.sh

agent-remove:  ## Stop and uninstall the agent daemon
	@bash scripts/agent-install.sh --uninstall

agent-start:  ## Start the agent daemon (must be installed first)
	launchctl kickstart -k "gui/$$(id -u)/$(LABEL)"

agent-stop:  ## Stop the agent daemon (restarts at next login — use agent-remove to uninstall)
	launchctl kill SIGTERM "gui/$$(id -u)/$(LABEL)" 2>/dev/null || true

agent-logs:  ## Tail live agent logs
	@mkdir -p $(LOG_DIR)
	@tail -f $(LOG_DIR)/out.log $(LOG_DIR)/err.log

agent-status:  ## Show whether the agent daemon is running
	@launchctl list | grep "$(LABEL)" || echo "$(LABEL) is not loaded"

agent-once:  ## Run the agent runner once (claims one WO then exits) — useful for testing
	@bash services/agent-runner/run-local.sh --once

# ── Documentation ────────────────────────────────────────────────────────────

docs-check:  ## Check factory wiki for stale pages (90-day threshold)
	python scripts/docs_stale_check.py --ignore-empty-wos

docs-check-strict:  ## Check factory wiki — flag stale AND empty covers_wos
	python scripts/docs_stale_check.py

docs-gdrive:  ## Sync factory docs to Google Drive (requires GDRIVE_* env vars)
	python scripts/publish_to_gdrive.py

docs-gdrive-dry:  ## Preview Google Drive sync without writing
	python scripts/publish_to_gdrive.py --dry-run

# ── Oryntra Chrome extension ──────────────────────────────────────────────────

oryntra-open:  ## Open Chrome extension manager so you can load Oryntra unpacked
	@echo "Load Oryntra unpacked:"
	@echo "  1. Open Chrome → chrome://extensions"
	@echo "  2. Enable Developer mode (top right toggle)"
	@echo "  3. Click 'Load unpacked' → select:"
	@echo "     $(shell cd ../sgerhart/Oryntra 2>/dev/null && pwd || echo '<path-to-Oryntra-repo>')"
	@open "chrome://extensions" 2>/dev/null || echo "  (couldn't auto-open Chrome)"
