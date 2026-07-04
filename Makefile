# Dentro AI Factory — Makefile

LABEL := com.dentroio.factory-agent
LOG_DIR := $(HOME)/Library/Logs/factory-agent

.PHONY: help \
        up down logs restart \
        agent-install agent-remove agent-start agent-stop agent-logs agent-status agent-once \
        oryntra-open

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Docker Compose (dashboard + orchestrator + watchdog) ─────────────────────

up:  ## Start factory services (status site + orchestrator + watchdog)
	docker compose -f docker-compose.status.yml up -d
	@echo "Dashboard: http://localhost:8099   Orchestrator: http://localhost:8100"

down:  ## Stop all factory services
	docker compose -f docker-compose.status.yml down

logs:  ## Tail logs for all factory services
	docker compose -f docker-compose.status.yml logs -f

restart:  ## Rebuild and restart all factory services
	docker compose -f docker-compose.status.yml build
	docker compose -f docker-compose.status.yml up -d --force-recreate

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

# ── Oryntra Chrome extension ──────────────────────────────────────────────────

oryntra-open:  ## Open Chrome extension manager so you can load Oryntra unpacked
	@echo "Load Oryntra unpacked:"
	@echo "  1. Open Chrome → chrome://extensions"
	@echo "  2. Enable Developer mode (top right toggle)"
	@echo "  3. Click 'Load unpacked' → select:"
	@echo "     $(shell cd ../sgerhart/Oryntra 2>/dev/null && pwd || echo '<path-to-Oryntra-repo>')"
	@open "chrome://extensions" 2>/dev/null || echo "  (couldn't auto-open Chrome)"
