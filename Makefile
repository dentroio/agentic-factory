# Dentro AI Factory — Makefile

LABEL := com.dentroio.factory-agent
LOG_DIR := $(HOME)/Library/Logs/factory-agent
PYTHON ?= python3

.PHONY: help \
        agent-setup \
        test pre-pr-check secrets ci-local \
        up down logs restart \
        agent-install agent-remove agent-start agent-stop agent-logs agent-status agent-once \
        docs-check docs-check-strict docs-gdrive \
        oryntra-open

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

agent-setup:  ## First-time setup — stores secrets in macOS Keychain
	@bash scripts/agent-setup.sh

# ── CI gate ──────────────────────────────────────────────────────────────────
# `make ci-local` is documented across AGENT_PROCESS.md, README.md, CLAUDE.md,
# AGENTS.md and the Cursor rules as the contract every agent runs before a PR,
# and services/agent-runner/quality_gate.py executes it as a real subprocess.
# It existed only in Makefile.template, so for every agent that followed the
# instructions it failed with "No rule to make target".
#
# The template's version composes lint/test/check-migrations/build. This repo's
# CI enforces unit tests plus Gitleaks. Add a step here only when ci.yml grows
# one; tests/unit/test_ci_local_mirrors_ci.py fails if the two drift apart.

test:  ## Run unit tests — must stay identical to the Unit Tests job in ci.yml
	@$(PYTHON) -c "import pytest" 2>/dev/null || { \
	  echo "pytest is not installed for $(PYTHON)."; \
	  echo "Install the same set ci.yml does:  $(PYTHON) -m pip install pytest pytest-asyncio httpx PyYAML"; \
	  exit 1; }
	$(PYTHON) -m pytest tests/unit/ -v --tb=short
	test_files=$$(find tests/unit -name 'test_*.py' | wc -l); test "$$test_files" -ge 20

pre-pr-check:  ## Static pre-PR check — the patterns the AI reviewer flags, no API call
	$(PYTHON) scripts/pre_pr_check.py

secrets:  ## Scan committed git history for secrets — must stay identical to the Gitleaks job in ci.yml
	@command -v gitleaks >/dev/null || { \
	  echo "gitleaks is not installed for this machine."; \
	  echo "Install it the same way CI does conceptually:  brew install gitleaks"; \
	  exit 1; }
	gitleaks detect --source . --redact --exit-code 1

ci-local:  ## Full PR gate locally — run this before every PR
	$(MAKE) test
	$(MAKE) pre-pr-check
	$(MAKE) secrets

# ── Docker Compose (dashboard + orchestrator + watchdog) ─────────────────────

up:  ## Start factory services (reads secrets from macOS Keychain if available)
	@bash scripts/compose-with-env.sh up -d
	@echo "Dashboard: http://localhost:8099   Orchestrator: http://localhost:8100 (localhost only)"

vault-export-keys:  ## Save Vault unseal key to macOS Keychain (root token stays offline)
	@echo "Reading Vault unseal key from Docker volume..."
	@if docker run --rm -v agentic-factory_vault-keys:/vault/keys:ro alpine \
		cat /vault/keys/unseal_key 2>/dev/null \
		| $(PYTHON) scripts/keychain_set.py dentroio-factory VAULT_UNSEAL_KEY; then \
		$(PYTHON) scripts/keychain_set.py --delete dentroio-factory VAULT_ROOT_TOKEN; \
		echo "  Unseal key saved to Keychain. Root token was not copied (AF-10)."; \
	else \
		echo "  ERROR: Could not read from vault-keys volume. Is the factory running? (make up)"; \
		exit 1; \
	fi

down:  ## Stop all factory services
	docker compose -f docker-compose.status.yml down

logs:  ## Tail logs for all factory services
	docker compose -f docker-compose.status.yml logs -f

restart:  ## Rebuild and restart all factory services
	docker compose -f docker-compose.status.yml build
	@bash scripts/compose-with-env.sh up -d --force-recreate

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
