#!/usr/bin/env bash
# Run docker compose with Keychain secrets in a 0600 temp env file (AF-12).
# Never writes .env.runtime into the repo. Deletes the temp file on exit.
#
# Usage: bash scripts/compose-with-env.sh up -d
#        bash scripts/compose-with-env.sh up -d --force-recreate
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/factory-env.XXXXXX")"
chmod 600 "$ENV_FILE"
cleanup() { rm -f "$ENV_FILE"; }
trap cleanup EXIT

FACTORY_ENV_SCRIPT="${FACTORY_ENV_SCRIPT:-$ROOT/scripts/factory-env.sh}"
set +e
bash "$FACTORY_ENV_SCRIPT" > "$ENV_FILE" 2>/dev/null
set -e

COMPOSE=(docker compose -f docker-compose.status.yml)
if [ -s "$ENV_FILE" ]; then
    "${COMPOSE[@]}" --env-file "$ENV_FILE" "$@"
else
    "${COMPOSE[@]}" "$@"
fi
