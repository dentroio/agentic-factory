#!/usr/bin/env bash
# run-reviewer.sh — start the Claude PR reviewer daemon (no AI backend needed beyond claude CLI).
#
# This daemon polls for pending factory validations, reviews PR diffs with Claude,
# and auto-approves backend-only changes or requests human sign-off for UI changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── PATH setup (matches run-local.sh) ─────────────────────────────────────────
for p in "$HOME/.local/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
    case ":$PATH:" in *":$p:"*) ;; *) export PATH="$p:$PATH" ;; esac
done

if command -v npm &>/dev/null; then
    NPM_BIN="$(npm prefix -g 2>/dev/null)/bin"
    case ":$PATH:" in *":$NPM_BIN:"*) ;; *) export PATH="$NPM_BIN:$PATH" ;; esac
fi

# ── Find Claude CLI ────────────────────────────────────────────────────────────
if ! command -v claude &>/dev/null; then
    for candidate in \
        "$HOME/Library/Application Support/Claude/claude-code/"*/claude.app/Contents/MacOS/claude \
        "$HOME/.cursor/extensions/"anthropic.claude-code-*/resources/native-binary/claude; do
        if [ -x "$candidate" ]; then
            export PATH="$(dirname "$candidate"):$PATH"
            break
        fi
    done
fi

# ── Load secrets (Keychain first, then .env) ──────────────────────────────────
FACTORY_ENV="$REPO_ROOT/scripts/factory-env.sh"
if [ -f "$FACTORY_ENV" ]; then
    while IFS='=' read -r key val; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        export "$key"="$val"
    done < <(bash "$FACTORY_ENV" 2>/dev/null)
fi

ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    set -o allexport
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +o allexport
fi

export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8100}"

# ── Activate venv if present ──────────────────────────────────────────────────
VENV="$SCRIPT_DIR/.venv"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1090
    source "$VENV/bin/activate"
fi

echo "[reviewer] Starting Claude PR reviewer daemon (orchestrator=$ORCHESTRATOR_URL)"
cd "$SCRIPT_DIR"
exec python3 reviewer.py
