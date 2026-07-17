#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$SCRIPT_DIR"

# Load .env
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  set -o allexport; source "$ENV_FILE"; set +o allexport
fi

export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8100}"
export LOCAL_REPO_PATH="${LOCAL_REPO_PATH:-}"
export GITHUB_REPO="${GITHUB_REPO:-}"
export RUNNER_HOST="${RUNNER_HOST:-192.168.10.15}"
export RUNNER_USER="${RUNNER_USER:-steve}"
export RUNNER_PASS="${RUNNER_PASS:-}"

# Ensure homebrew tools (sshpass, gh, etc.) are on PATH
for p in "/opt/homebrew/bin" "/usr/local/bin" "$HOME/.local/bin"; do
  case ":$PATH:" in *":$p:"*) ;; *) export PATH="$p:$PATH" ;; esac
done

# Use venv python (3.11) if available
VENV="$SCRIPT_DIR/.venv"
if [ -d "$VENV" ]; then source "$VENV/bin/activate"; fi

echo "[health-agent] Starting factory health monitor (orchestrator=$ORCHESTRATOR_URL)"
exec python3 health_agent.py
