#!/usr/bin/env bash
# run-local.sh — start the factory agent runner on a Mac host (no Docker required).
#
# Supports all four AI backends using your existing subscriptions — no raw API keys needed:
#
#   claude  Install: curl -fsSL https://claude.ai/install.sh | bash
#           Auth:    claude login   (Claude Pro/Max subscription)
#
#   cursor  Install: curl https://cursor.com/install -fsS | bash
#           Auth:    CURSOR_API_KEY in .env  (Cursor subscription)
#
#   codex   Install: npm install -g @openai/codex
#           Auth:    codex login   (OpenAI/ChatGPT subscription)
#
#   gemini  Install: npm install -g @google/gemini-cli
#           Auth:    gemini        (first run — Google OAuth / Gemini subscription)
#
# Usage: ./run-local.sh [--once]   (--once claims one WO then exits; default loops forever)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Build PATH that includes all subscription CLI install locations ───────────
# Order: user local bins first, then Homebrew, then system
EXTRA_PATHS=(
    "$HOME/.local/bin"                        # Cursor agent CLI (curl install)
    "$HOME/.npm/bin"                          # npm global bins (some configs)
    "/opt/homebrew/bin"                       # Homebrew (Apple Silicon)
    "/usr/local/bin"                          # Homebrew (Intel) / manual installs
)
for p in "${EXTRA_PATHS[@]}"; do
    case ":$PATH:" in
        *":$p:"*) ;;
        *) export PATH="$p:$PATH" ;;
    esac
done

# Add Node.js global bin (npm -g prefix varies by install method)
if command -v npm &>/dev/null; then
    NPM_BIN="$(npm prefix -g 2>/dev/null)/bin"
    case ":$PATH:" in
        *":$NPM_BIN:"*) ;;
        *) export PATH="$NPM_BIN:$PATH" ;;
    esac
fi

# ── Find Claude CLI (inside app bundle — version number changes with updates) ─
if ! command -v claude &>/dev/null; then
    CLAUDE_BIN=""
    for pattern in \
        "$HOME/Library/Application Support/Claude/claude-code/"*/claude.app/Contents/MacOS/claude \
        "$HOME/Library/Application Support/Claude/claude-code-vm/"*/claude \
        "$HOME/.cursor/extensions/"anthropic.claude-code-*/resources/native-binary/claude; do
        # shellcheck disable=SC2086
        LATEST=$(ls -t $pattern 2>/dev/null | head -1)
        if [ -x "$LATEST" ]; then
            CLAUDE_BIN="$LATEST"
            break
        fi
    done
    if [ -n "$CLAUDE_BIN" ]; then
        CLAUDE_DIR="$(dirname "$CLAUDE_BIN")"
        export PATH="$CLAUDE_DIR:$PATH"
        echo "[factory-agent] Found claude: $CLAUDE_BIN"
    fi
fi

# ── Source .env ────────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    set -o allexport
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +o allexport
    echo "[factory-agent] Loaded .env from $ENV_FILE"
else
    echo "[factory-agent] WARNING: No .env at $ENV_FILE — relying on environment" >&2
fi

# ── Local overrides (Docker internal paths don't work on the host) ────────────
export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8100}"
export WORKTREE_BASE="${WORKTREE_BASE:-$HOME/workspace/factory-worktrees}"
mkdir -p "$WORKTREE_BASE"

# ── Verify chosen backend is available ────────────────────────────────────────
AGENT="${PREFERRED_AGENT:-claude}"
case "$AGENT" in
    claude)
        if ! command -v claude &>/dev/null; then
            echo "[factory-agent] ERROR: claude not found. Install: curl -fsSL https://claude.ai/install.sh | bash" >&2; exit 1
        fi
        echo "[factory-agent] Backend: claude ($(claude --version 2>/dev/null | head -1))"
        ;;
    cursor)
        if ! command -v agent &>/dev/null && [ ! -x "$HOME/.local/bin/agent" ]; then
            echo "[factory-agent] ERROR: Cursor agent not found. Install: curl https://cursor.com/install -fsS | bash" >&2; exit 1
        fi
        echo "[factory-agent] Backend: cursor/agent"
        ;;
    codex)
        if ! command -v codex &>/dev/null; then
            echo "[factory-agent] ERROR: codex not found. Install: npm install -g @openai/codex" >&2; exit 1
        fi
        echo "[factory-agent] Backend: codex ($(codex --version 2>/dev/null | head -1))"
        ;;
    gemini)
        if ! command -v gemini &>/dev/null; then
            echo "[factory-agent] ERROR: gemini not found. Install: npm install -g @google/gemini-cli" >&2; exit 1
        fi
        echo "[factory-agent] Backend: gemini ($(gemini --version 2>/dev/null | head -1))"
        ;;
    *)
        echo "[factory-agent] WARNING: Unknown backend '$AGENT', defaulting to claude" >&2
        ;;
esac

# ── Python venv (optional) ────────────────────────────────────────────────────
VENV="$SCRIPT_DIR/.venv"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1090
    source "$VENV/bin/activate"
fi

# ── Run ───────────────────────────────────────────────────────────────────────
echo "[factory-agent] Starting (agent=$AGENT, repo=${GITHUB_REPO:-?}, worktrees=$WORKTREE_BASE)"
cd "$SCRIPT_DIR"
exec python3 runner.py "$@"
