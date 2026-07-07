#!/usr/bin/env bash
# agent-setup.sh — Interactive first-time setup for the AI Factory agent.
# Stores secrets in macOS Keychain (no .env editing needed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PREFS_FILE="$HOME/.config/factory-agent/prefs"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         Dentro AI Factory — First-Time Setup         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Secrets are stored in macOS Keychain (service: dentroio-factory)."
echo "Non-secrets are stored in $PREFS_FILE"
echo ""

_store_keychain() {
    local key="$1" val="$2"
    if [ -z "$val" ]; then
        return
    fi
    # Delete existing entry silently, then add new one
    security delete-generic-password -s "dentroio-factory" -a "$key" 2>/dev/null || true
    security add-generic-password -s "dentroio-factory" -a "$key" -w "$val" 2>/dev/null
    echo "  [keychain] $key stored"
}

# GitHub Token
echo "── GitHub Token ─────────────────────────────────────────"
echo "  Required. Format: ghp_... or github_pat_..."
echo "  Scopes needed: repo, read:org"
printf "  Token: "
read -rs GITHUB_TOKEN_VAL
echo ""
_store_keychain "GITHUB_TOKEN" "$GITHUB_TOKEN_VAL"

# GitHub Repo
echo ""
echo "── GitHub Repo ─────────────────────────────────────────"
echo "  Primary repo the factory monitors (format: owner/repo)"
printf "  Repo: "
read -r GITHUB_REPO_VAL
echo ""

# Cursor API Key (optional)
echo ""
echo "── Cursor API Key (optional) ────────────────────────────"
echo "  Required only if PREFERRED_AGENT=cursor"
echo "  Press Enter to skip."
printf "  Key: "
read -rs CURSOR_KEY_VAL
echo ""
_store_keychain "CURSOR_API_KEY" "$CURSOR_KEY_VAL"

# ntfy Topic — auto-generate a hard-to-guess name
echo ""
echo "── ntfy Push Notifications ──────────────────────────────"
NTFY_TOPIC_VAL="factory-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom 2>/dev/null | head -c 14 || openssl rand -hex 7)"
echo "  Auto-generated topic: $NTFY_TOPIC_VAL"
echo "  Subscribe at: https://ntfy.sh/$NTFY_TOPIC_VAL"
echo "  (Add this URL in the ntfy app — https://ntfy.sh)"
_store_keychain "NTFY_TOPIC" "$NTFY_TOPIC_VAL"
_store_keychain "NTFY_SERVER" "https://ntfy.sh"

# Slack Webhook (optional)
echo ""
echo "── Slack Webhook URL (optional) ─────────────────────────"
echo "  For notifications to a Slack channel. Press Enter to skip."
printf "  URL: "
read -rs SLACK_WEBHOOK_VAL
echo ""
_store_keychain "SLACK_WEBHOOK_URL" "$SLACK_WEBHOOK_VAL"

# Anthropic API Key (for WO spec generation in orchestrator)
echo ""
echo "── Anthropic API Key (for WO spec generation) ──────────"
echo "  Used by the orchestrator to generate WO specs from plain-English"
echo "  descriptions. Get it at https://console.anthropic.com/settings/keys"
echo "  Press Enter to skip (you can add it later)."
printf "  Key: "
read -rs ANTHROPIC_KEY_VAL
echo ""
_store_keychain "ANTHROPIC_API_KEY" "$ANTHROPIC_KEY_VAL"

# Preferred agent backend
echo ""
echo "── Agent Backend ────────────────────────────────────────"
echo "  Which AI runs your work orders?"
echo "    1) claude  (Claude Pro/Max — recommended)"
echo "    2) cursor  (Cursor subscription)"
echo "    3) codex   (OpenAI/ChatGPT subscription)"
echo "    4) gemini  (Google Gemini subscription)"
printf "  Choice [1-4, default 1]: "
read -r AGENT_CHOICE
echo ""

case "$AGENT_CHOICE" in
    2) PREFERRED_AGENT="cursor" ;;
    3) PREFERRED_AGENT="codex" ;;
    4) PREFERRED_AGENT="gemini" ;;
    *) PREFERRED_AGENT="claude" ;;
esac
echo "  Selected: $PREFERRED_AGENT"

# Store non-secrets in prefs file
mkdir -p "$(dirname "$PREFS_FILE")"
{
    echo "GITHUB_REPO=$GITHUB_REPO_VAL"
    echo "PREFERRED_AGENT=$PREFERRED_AGENT"
} > "$PREFS_FILE"
echo "  [prefs] GITHUB_REPO and PREFERRED_AGENT saved to $PREFS_FILE"

echo ""
echo "────────────────────────────────────────────────────────"
echo "Setup complete. Starting factory services..."
echo ""

cd "$REPO_ROOT"
bash scripts/factory-env.sh > .env.runtime 2>/dev/null || true
if [ -s .env.runtime ]; then
    docker compose -f docker-compose.status.yml --env-file .env.runtime up -d
else
    docker compose -f docker-compose.status.yml up -d
fi
rm -f .env.runtime

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Factory is running!"
echo ""
echo "  Dashboard:    http://localhost:8099"
echo "  Settings UI:  http://localhost:8099/settings/agents"
echo "  Orchestrator: http://localhost:8100"
echo ""
echo "  To install the agent daemon:"
echo "    make agent-install"
echo ""
echo "  To run the agent once (test a WO):"
echo "    make agent-once"
echo "════════════════════════════════════════════════════════"

open "http://localhost:8099/settings/agents" 2>/dev/null || true
