#!/usr/bin/env bash
# agent-install.sh — install the factory agent runner as a macOS launchd daemon.
#
# Run once after cloning the repo and filling in .env.
# After install, the agent starts automatically at login and restarts on crash.
#
# Usage:
#   ./scripts/agent-install.sh           # install and start
#   ./scripts/agent-install.sh --uninstall  # stop and remove

set -euo pipefail

LABEL="com.dentroio.factory-agent"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_RUNNER="$REPO_ROOT/services/agent-runner"
LOG_DIR="$HOME/Library/Logs/factory-agent"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Stopping and unloading $LABEL..."
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo "Done. Plist removed from $PLIST_DEST"
    echo "Log files remain at $LOG_DIR — remove manually if desired."
    exit 0
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────

# Load credentials: Keychain first, then .env fallback
FACTORY_ENV_SH="$REPO_ROOT/scripts/factory-env.sh"
if [ -f "$FACTORY_ENV_SH" ]; then
    while IFS='=' read -r key val; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        export "$key"="$val"
    done < <(bash "$FACTORY_ENV_SH" 2>/dev/null)
fi

# Fall back to .env if Keychain didn't supply what we need
if [ -f "$REPO_ROOT/.env" ] && { [ -z "${GITHUB_TOKEN:-}" ] || [ -z "${GITHUB_REPO:-}" ]; }; then
    # shellcheck disable=SC1090
    set -o allexport; source "$REPO_ROOT/.env"; set +o allexport
fi

# Check GITHUB_TOKEN and GITHUB_REPO are set (from either source)
if [ -z "${GITHUB_TOKEN:-}" ] || [ -z "${GITHUB_REPO:-}" ]; then
    echo "ERROR: GITHUB_TOKEN and GITHUB_REPO not found."
    echo "Run 'make agent-setup' to store credentials in macOS Keychain, or create a .env file."
    exit 1
fi

# Check Python 3 is available
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found in PATH. Install Python 3 (brew install python)."
    exit 1
fi

# Install Python dependencies into a local venv if not already there
VENV="$AGENT_RUNNER/.venv"
if [ ! -d "$VENV" ]; then
    echo "Creating Python venv at $VENV..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet -r "$AGENT_RUNNER/requirements.txt"
    echo "Dependencies installed."
else
    echo "Venv already exists — skipping pip install (run 'pip install -r requirements.txt' to update)."
fi

# ── Create log directory ──────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
echo "Logs will go to $LOG_DIR"

# ── Write plist ───────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$PLIST_DEST")"

sed \
    -e "s|AGENT_RUNNER_PATH|$AGENT_RUNNER|g" \
    -e "s|LOG_PATH|$LOG_DIR|g" \
    "$SCRIPT_DIR/com.dentroio.factory-agent.plist" \
    > "$PLIST_DEST"

echo "Plist written to $PLIST_DEST"

# ── Load (or reload) ──────────────────────────────────────────────────────────
# Unload first in case it was previously installed
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

echo ""
echo "Factory agent installed and started."
echo ""
echo "Commands:"
echo "  make agent-logs    # tail live logs"
echo "  make agent-status  # show launchd status"
echo "  make agent-stop    # stop (will restart at next login)"
echo "  make agent-start   # restart now"
echo "  make agent-remove  # uninstall completely"
