#!/usr/bin/env bash
# pr_watch.sh — Own the full WO lifecycle: watch until MERGED, sync, deploy
#
# Usage:
#   bash scripts/pr_watch.sh [pr-number]
#   make pr-watch               # auto-detects PR for current branch
#   PR_WATCH_TIMEOUT=7200 make pr-watch   # extend for P1 PRs awaiting human review
#
# Environment:
#   PR_WATCH_TIMEOUT  seconds before giving up          (default: 7200 = 2 hours)
#   PR_WATCH_POLL     seconds between status checks     (default: 60)
#
# Full lifecycle owned by this script:
#   - Polls gh pr checks every POLL seconds
#   - Lint failure → make format → commit [pr-watch-fix] → push (max 2 times)
#   - Branch out of date → merge main → push
#   - Cloud commits (applier, ci-auto-fix) → git pull --rebase → make deploy-changed
#   - Claude Code Review "Needs attention" → posts advisory comment, merge allowed
#   - Claude Code Review "Review required" → exit 1; agent must fix the code and push
#   - P2 (auto-merge) → waits for MERGED; on merge: pull main + make deploy-changed
#   - P1 (human review) → prints review URL, keeps polling until human MERGES or CLOSES
#   - On MERGED: git checkout main, pull, make deploy-changed, WO complete

set -euo pipefail

# ── Argument + environment ────────────────────────────────────────────────────

PR_NUMBER="${1:-}"
if [ -z "$PR_NUMBER" ]; then
    PR_NUMBER=$(gh pr view --json number -q '.number' 2>/dev/null || echo "")
fi
if [ -z "$PR_NUMBER" ]; then
    echo "ERROR: Could not detect a PR for the current branch."
    echo "Usage: bash scripts/pr_watch.sh <pr-number>"
    echo "       or: run from a branch that has an open PR"
    exit 1
fi

TIMEOUT=${PR_WATCH_TIMEOUT:-7200}   # 2 hours — P1 PRs may wait for human review
POLL=${PR_WATCH_POLL:-60}
MAX_LINT_FIX=2

# ── Colors ────────────────────────────────────────────────────────────────────

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[1;33m'
CYAN='\033[36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; }
hdr()  { echo -e "\n${BOLD}$*${NC}"; }

# ── Get PR metadata ───────────────────────────────────────────────────────────

PR_JSON=$(gh pr view "$PR_NUMBER" --json headRefName,autoMergeRequest,url,title 2>/dev/null)
BRANCH=$(echo "$PR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['headRefName'])")
PR_URL=$(echo "$PR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['url'])")
PR_TITLE=$(echo "$PR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['title'])")
AUTO_MERGE=$(echo "$PR_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('true' if d.get('autoMergeRequest') else 'false')
")

hdr "▶  PR Watch — #${PR_NUMBER}"
echo "   Title:   ${PR_TITLE}"
echo "   Branch:  ${BRANCH}"
echo "   URL:     ${PR_URL}"
echo "   Timeout: ${TIMEOUT}s | Poll: ${POLL}s | Max lint fixes: ${MAX_LINT_FIX}"
if [ "$AUTO_MERGE" = "true" ]; then
    echo -e "   Mode:    ${GREEN}P2 — auto-merge enabled; will wait for merge to land on main${NC}"
else
    echo -e "   Mode:    ${YELLOW}P1 — will wait for human review then handle merge locally${NC}"
fi
echo ""

# ── Helpers ───────────────────────────────────────────────────────────────────

deploy_changed() {
    # Re-deploy services/containers affected by new commits.
    # If your project uses Docker Compose, add a `deploy-changed` Makefile target.
    # If your project uses a different deploy mechanism, replace this call.
    if make -n deploy-changed --no-print-directory &>/dev/null; then
        make deploy-changed --no-print-directory || true
    else
        log "No deploy-changed Makefile target — skipping local redeploy"
        log "Add 'deploy-changed' to your Makefile to auto-redeploy on merge."
    fi
}

sync_branch() {
    git fetch origin --quiet
    before=$(git rev-parse HEAD)
    if git pull --rebase origin "$BRANCH" --quiet 2>/dev/null; then
        after=$(git rev-parse HEAD)
        if [ "$before" != "$after" ]; then
            warn "Cloud commits pulled onto ${BRANCH}:"
            git log --oneline "${before}..${after}" | sed 's/^/   /'
            echo ""
            # Re-deploy if source changed in these cloud commits (applier, ci-auto-fix, etc.)
            deploy_changed
        fi
    else
        warn "Rebase had conflicts — attempting abort and merge fallback"
        git rebase --abort 2>/dev/null || true
        git merge "origin/${BRANCH}" --no-edit --quiet 2>/dev/null || true
    fi
}

count_watch_fixes() {
    git log --oneline HEAD ^"origin/main" 2>/dev/null | grep -c "\[pr-watch-fix\]" || echo 0
}

fix_lint() {
    local fixes_so_far
    fixes_so_far=$(count_watch_fixes)
    if [ "$fixes_so_far" -ge "$MAX_LINT_FIX" ]; then
        fail "Lint fix limit reached (${MAX_LINT_FIX}). Manual fix required."
        echo "   Run: make format && git add -A && git commit -m 'fix(lint): ...' && git push"
        return 1
    fi

    log "Auto-fixing lint with make format..."
    sync_branch

    if ! make format --no-print-directory 2>&1; then
        fail "make format failed — manual fix required"
        return 1
    fi

    if git diff --quiet && git diff --cached --quiet; then
        warn "make format ran but no files changed."
        warn "The lint failure may need manual investigation."
        return 1
    fi

    local attempt=$(( fixes_so_far + 1 ))
    git add -A
    git commit -m "fix(lint): auto-fix lint [pr-watch-fix] attempt ${attempt}/${MAX_LINT_FIX}

Auto-fixed by pr_watch.sh.
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    git push origin "$BRANCH"
    ok "Lint fix pushed (attempt ${attempt}/${MAX_LINT_FIX}) — CI re-running"
    echo ""
    return 0
}

fix_out_of_date() {
    log "Branch is out of date — merging main..."
    sync_branch
    git fetch origin main --quiet
    if git merge origin/main --no-edit --quiet 2>/dev/null; then
        git push origin "$BRANCH"
        ok "Merged origin/main into ${BRANCH} and pushed"
        echo ""
    else
        fail "Merge conflict when pulling main — manual resolution required"
        git merge --abort 2>/dev/null || true
        return 1
    fi
}

get_checks() {
    gh pr checks "$PR_NUMBER" --json name,conclusion,status 2>/dev/null || echo "[]"
}

get_pr_state() {
    gh pr view "$PR_NUMBER" --json state -q '.state' 2>/dev/null || echo "UNKNOWN"
}

check_ai_review() {
    # Returns: lgtm | warn | block | pending
    local verdict
    verdict=$(gh pr view "$PR_NUMBER" --json comments -q '
      [.comments[] | select(.body | (contains("AI Code Review") or contains("## Code Review")))] |
      last |
      if . == null then "pending"
      elif .body | contains("Review required") then "block"
      elif .body | contains("Needs attention") then "warn"
      else "lgtm"
      end
    ' 2>/dev/null || echo "pending")
    echo "$verdict"
}

# ── Main loop ─────────────────────────────────────────────────────────────────

start=$(date +%s)
consecutive_all_passing=0   # require 2 consecutive all-pass polls before declaring done

while true; do
    now=$(date +%s)
    elapsed=$(( now - start ))
    remaining=$(( TIMEOUT - elapsed ))

    if [ $elapsed -ge $TIMEOUT ]; then
        echo ""
        fail "Timeout after ${TIMEOUT}s — handing off to human"
        echo ""
        log "Current check status:"
        gh pr checks "$PR_NUMBER" 2>/dev/null || true
        echo ""
        echo "PR: ${PR_URL}"
        echo ""
        echo "To resume watching: make pr-watch PR=${PR_NUMBER}"
        exit 1
    fi

    # ── Check PR state (merged / closed) ──────────────────────────────────────
    state=$(get_pr_state)

    if [ "$state" = "MERGED" ]; then
        echo ""
        ok "PR #${PR_NUMBER} merged to main!"
        log "Updating local main..."

        git fetch origin main --quiet
        git checkout main --quiet
        BEFORE=$(git rev-parse HEAD)
        git pull origin main --quiet
        AFTER=$(git rev-parse HEAD)
        ok "Local main is now at $(git rev-parse --short HEAD)."

        if [ "$BEFORE" != "$AFTER" ]; then
            echo ""
            log "Re-deploying services affected by merged PR #${PR_NUMBER}..."
            deploy_changed
        else
            log "Local main was already up to date — no redeploy needed."
        fi

        echo ""
        log "Branch ${BRANCH} can now be deleted:"
        echo "   git branch -D ${BRANCH}"
        echo "   git push origin --delete ${BRANCH}"
        echo ""
        exit 0
    fi

    if [ "$state" = "CLOSED" ]; then
        warn "PR #${PR_NUMBER} was closed without merging."
        exit 1
    fi

    # ── Get check results ─────────────────────────────────────────────────────
    checks_json=$(get_checks)

    total=$(echo "$checks_json" | python3 -c "
import json,sys; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "0")

    pending=$(echo "$checks_json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(sum(1 for c in d if c.get('status') in ('queued','in_progress') or c.get('conclusion') is None))" 2>/dev/null || echo "0")

    failed=$(echo "$checks_json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(sum(1 for c in d if c.get('conclusion') == 'failure'))" 2>/dev/null || echo "0")

    passed=$(echo "$checks_json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(sum(1 for c in d if c.get('conclusion') in ('success','skipped','neutral')))" 2>/dev/null || echo "0")

    log "[${elapsed}s elapsed, ${remaining}s remaining] ${passed}/${total} passed | ${pending} pending | ${failed} failed"

    # ── Handle failures ───────────────────────────────────────────────────────
    if [ "$failed" -gt 0 ]; then
        consecutive_all_passing=0

        failed_names=$(echo "$checks_json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
names=[c['name'] for c in d if c.get('conclusion')=='failure']
print('\n'.join(names))" 2>/dev/null || echo "unknown")

        echo ""
        fail "Failed checks:"
        echo "$failed_names" | while IFS= read -r name; do
            echo "   - $name"
        done
        echo ""

        # Is it a lint failure?
        if echo "$failed_names" | grep -qi "lint\|format\|style"; then
            warn "Lint failure detected — attempting auto-fix..."
            if fix_lint; then
                log "Lint fix pushed. Waiting ${POLL}s for CI to re-trigger..."
                sleep "$POLL"
                continue
            else
                exit 1
            fi
        fi

        # Is the branch out of date?
        if echo "$failed_names" | grep -qi "out.of.date\|behind base\|base branch"; then
            fix_out_of_date || exit 1
            sleep 10
            continue
        fi

        # Claude Code Review failure — "Review required" blocks; "Needs attention" is advisory
        if echo "$failed_names" | grep -qi "claude\|ai.*review\|code.*review"; then
            ai_verdict=$(check_ai_review)
            if [ "$ai_verdict" = "block" ]; then
                echo ""
                fail "AI review verdict: Review required — merge blocked."
                fail "Read the review comment, fix the code, run make ci-local, then push."
                echo ""
                echo "PR: ${PR_URL}"
                exit 1
            else
                # "Needs attention" — informational; cloud ai-review-applier.yml may apply suggestions
                warn "Claude Code Review: Needs attention — advisory only; syncing and retrying..."
                sync_branch
            fi
            sleep "$POLL"
            continue
        fi

        # Other non-lint failure — wait for cloud ci-auto-fix.yml
        warn "CI failure in: $(echo "$failed_names" | tr '\n' ' ')"
        warn "Waiting for cloud ci-auto-fix.yml to attempt a fix..."
        sync_branch
        warn "Retrying in ${POLL}s..."

    # ── Handle pending ────────────────────────────────────────────────────────
    elif [ "$pending" -gt 0 ]; then
        consecutive_all_passing=0
        printf "   %s check(s) still running... (next poll in %ss)\r" "$pending" "$POLL"

    # ── All checks complete (no failures, no pending) ─────────────────────────
    else
        consecutive_all_passing=$(( consecutive_all_passing + 1 ))

        if [ "$consecutive_all_passing" -lt 2 ]; then
            log "All checks complete — confirming on next poll (${consecutive_all_passing}/2)..."
        else
            echo ""
            ok "All ${total} CI checks passed!"
            echo ""

            log "Checking AI review verdict..."
            ai_verdict=$(check_ai_review)

            case "$ai_verdict" in
                block)
                    fail "AI review verdict: Review required — merge blocked"
                    fail "Fix the issues flagged in the AI review comment, then push."
                    echo ""
                    echo "PR: ${PR_URL}"
                    exit 1
                    ;;
                warn)
                    warn "AI review verdict: Needs attention (advisory — merge still allowed)"
                    sync_branch
                    ;;
                lgtm)
                    ok "AI review: LGTM"
                    ;;
                pending)
                    warn "AI review not yet posted — proceeding"
                    ;;
            esac

            # Both P1 and P2: keep polling until MERGED.
            if [ "$AUTO_MERGE" = "true" ]; then
                log "P2: all checks green — waiting for GitHub auto-merge to fire..."
            else
                echo ""
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ok  "PR #${PR_NUMBER} is fully green — waiting for human review + merge."
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo ""
                echo -e "${BOLD}  Review URL:${NC}  ${PR_URL}"
                echo ""
                echo "  Reviewer checklist:"
                echo "  1. Read the diff (focus on logic changes, not formatting)"
                echo "  2. Review any UI changes or test steps in the PR description"
                echo "  3. Approve and merge when satisfied (squash merge)"
                echo ""
                echo "  Watching for merge — this terminal must stay open."
                echo "  On merge: will pull main + redeploy affected services automatically."
                echo ""
                log "Continuing to poll for MERGED state (agent owns full lifecycle)..."
            fi
            consecutive_all_passing=1  # reset to keep polling for MERGED state
        fi
    fi

    sleep "$POLL"
done
