#!/usr/bin/env bash
# run-local.sh — start the factory agent runner on a Mac host (no Docker required).
#
# This script is called directly by the launchd plist. It finds the Claude CLI,
# sources the repo .env, overrides Docker-specific paths for local use, and starts
# the Python runner loop.
#
# Usage: ./run-local.sh [--once]   (--once claims one WO then exits; default loops forever)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Find Claude CLI ────────────────────────────────────────────────────────────
# Claude Code ships inside the app bundle. Find the latest installed version.
CLAUDE_BIN=""
for candidate in \
    "/usr/local/bin/claude" \
    "$HOME/.local/bin/claude" \
    "$HOME/.npm/bin/claude" \
    "$(ls -t "$HOME/Library/Application Support/Claude/claude-code/"*/claude.app/Contents/MacOS/claude 2>/dev/null | head -1)" \
    "$(ls -t "$HOME/Library/Application Support/Claude/claude-code-vm/"*/claude 2>/dev/null | head -1)" \
    "$(ls -t "$HOME/.cursor/extensions/"anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | head -1)"; do
    if [ -x "$candidate" ]; then
        CLAUDE_BIN="$candidate"
        break
    fi
done

if [ -z "$CLAUDE_BIN" ]; then
    echo "[factory-agent] ERROR: claude CLI not found. Install Claude Code or set CLAUDE_BIN env var." >&2
    exit 1
fi

# Make it available as 'claude' in PATH
CLAUDE_DIR="$(dirname "$CLAUDE_BIN")"
export PATH="$CLAUDE_DIR:$PATH"
echo "[factory-agent] Using claude: $CLAUDE_BIN"

# ── Source .env ────────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    # Export all non-comment, non-blank lines
    set -o allexport
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +o allexport
    echo "[factory-agent] Loaded .env from $ENV_FILE"
else
    echo "[factory-agent] WARNING: No .env found at $ENV_FILE — relying on environment variables" >&2
fi

# ── Local overrides (Docker paths don't work on the host) ─────────────────────
# Orchestrator is at localhost when running on the Mac (not Docker internal network)
export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8100}"

# Worktrees live on the local filesystem, not the Docker /workspace volume
export WORKTREE_BASE="${WORKTREE_BASE:-$HOME/workspace/factory-worktrees}"
mkdir -p "$WORKTREE_BASE"

# ── Python venv (optional) ────────────────────────────────────────────────────
VENV="$SCRIPT_DIR/.venv"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1090
    source "$VENV/bin/activate"
    echo "[factory-agent] Activated venv: $VENV"
fi

# ── Run ───────────────────────────────────────────────────────────────────────
echo "[factory-agent] Starting runner (agent=$PREFERRED_AGENT, repo=$GITHUB_REPO)"
cd "$SCRIPT_DIR"
exec python3 runner.py "$@"
