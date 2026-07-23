#!/usr/bin/env bash
# wo_start.sh — Create a WO branch + worktree with an optional orchestrator reservation.
#
# Usage:
#   NNN=1044 SLUG=my-feature ./scripts/wo_start.sh
#   SLUG=my-feature ./scripts/wo_start.sh   # auto-reserves from orchestrator when ORCHESTRATOR_URL is set
#
# Environment:
#   NNN             WO number (optional — reserved from orchestrator when unset)
#   SLUG            Short slug for the branch name (required)
#   ORCHESTRATOR_URL  Base URL of the orchestrator (e.g. http://localhost:8100)
#   API_SECRET      Bearer token for orchestrator auth (optional)

set -euo pipefail

if [ -z "${SLUG:-}" ]; then
    echo "Error: SLUG is required" >&2
    echo "Usage: NNN=1044 SLUG=my-feature $0" >&2
    exit 1
fi

# ── Auto-reserve WO number from orchestrator if NNN is unset ─────────────────
if [ -z "${NNN:-}" ]; then
    if [ -n "${ORCHESTRATOR_URL:-}" ]; then
        AUTH_HEADER=""
        if [ -n "${API_SECRET:-}" ]; then
            AUTH_HEADER="-H \"Authorization: Bearer ${API_SECRET}\""
        fi
        echo "Reserving WO number from ${ORCHESTRATOR_URL}..."
        RESP=$(curl -sf -X POST "${ORCHESTRATOR_URL}/api/wos/reserve" \
            -H "Content-Type: application/json" \
            ${AUTH_HEADER:+ -H "Authorization: Bearer ${API_SECRET}"} \
            -d "{\"title\": \"${SLUG}\", \"reserved_by\": \"$(whoami)\"}" 2>/dev/null) || true
        if [ -n "${RESP:-}" ]; then
            NNN=$(echo "${RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin)['number'])" 2>/dev/null) || true
        fi
        if [ -n "${NNN:-}" ]; then
            echo "Reserved WO-${NNN} (title: ${SLUG})"
        else
            echo "Warning: could not reach orchestrator — falling back to scan-based number" >&2
        fi
    fi

    if [ -z "${NNN:-}" ]; then
        # Scan-based fallback: max WO-NNN.md number + 1
        WO_DIR="${WO_DIR:-docs/work_orders}"
        if [ -d "${WO_DIR}" ]; then
            NNN=$(ls "${WO_DIR}"/WO-*.md 2>/dev/null \
                | sed 's|.*/WO-||; s|-.*||' \
                | sort -n | tail -1 || echo "999")
            NNN=$((NNN + 1))
            echo "Scan fallback: using WO-${NNN}"
        else
            echo "Error: could not determine WO number — set NNN= explicitly or configure ORCHESTRATOR_URL" >&2
            exit 1
        fi
    fi
fi

BRANCH="wo/${NNN}-${SLUG}"
WORKTREE_DIR=".worktrees/wo-${NNN}-${SLUG}"

echo "Creating branch ${BRANCH}..."
git checkout -b "${BRANCH}" 2>/dev/null || git checkout "${BRANCH}"
echo "Branch ready: ${BRANCH}"

# Create worktree if it doesn't exist
if [ ! -d "${WORKTREE_DIR}" ]; then
    git worktree add "${WORKTREE_DIR}" "${BRANCH}" 2>/dev/null || true
fi

echo ""
echo "WO-${NNN} workspace ready."
echo "  Branch:   ${BRANCH}"
if [ -d "${WORKTREE_DIR}" ]; then
    echo "  Worktree: ${WORKTREE_DIR}"
fi
