#!/usr/bin/env bash
# Reads factory secrets from macOS Keychain and prints KEY=VALUE for docker compose --env-file
# Usage: bash scripts/factory-env.sh > .env.runtime
# Silent on errors — missing Keychain entry = empty string

_kc() { security find-generic-password -s "dentroio-factory" -a "$1" -w 2>/dev/null || echo ""; }

GITHUB_TOKEN="$(_kc GITHUB_TOKEN)"
CURSOR_API_KEY="$(_kc CURSOR_API_KEY)"
NTFY_TOPIC="$(_kc NTFY_TOPIC)"
SLACK_WEBHOOK_URL="$(_kc SLACK_WEBHOOK_URL)"
ANTHROPIC_API_KEY="$(_kc ANTHROPIC_API_KEY)"

[ -n "$GITHUB_TOKEN" ] && echo "GITHUB_TOKEN=$GITHUB_TOKEN"
[ -n "$CURSOR_API_KEY" ] && echo "CURSOR_API_KEY=$CURSOR_API_KEY"
[ -n "$NTFY_TOPIC" ] && echo "NTFY_TOPIC=$NTFY_TOPIC"
[ -n "$SLACK_WEBHOOK_URL" ] && echo "SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
[ -n "$ANTHROPIC_API_KEY" ] && echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"

# Non-secrets from prefs file
PREFS_FILE="$HOME/.config/factory-agent/prefs"
if [ -f "$PREFS_FILE" ]; then
    while IFS='=' read -r key val; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        echo "$key=$val"
    done < "$PREFS_FILE"
fi
