# WO-1095 — Settings UI: Deploy & Harness (no file edits)

**Created:** 2026-09-07
**Priority:** P2
**Effort:** M
**Services:** orchestrator, status-site, agent-runner, docs
**Depends on:** WO-1094
**Status:** 🟡 In Progress

---

## Problem

CD and harness knobs (`FACTORY_CD_ENABLED`, tool allowlist, spend budget) require
GitHub Settings and host env/prefs edits. Operators who finished Get Started still
cannot enable deploy or tune the LLM harness from the dashboard.

## Goal

A **Settings → Deploy & Harness** page where operators can:

1. See whether a `factory-deploy` self-hosted runner is online (engine repo)
2. Toggle push-to-main CD (`FACTORY_CD_ENABLED`) without leaving the UI
3. Set tool policy + weekly spend budget into host prefs (picked up by `factory-env.sh`)

## Scope

**In scope:**
- Orchestrator APIs for engine-repo CD variable + Actions runners list
- Draft-server `/api/harness` GET/PUT for prefs keys
- Status-site page + Settings hub card + proxies
- BACKLOG.md / CAPABILITY_STATUS / Getting-Started / LLM-Harness updates

**Out of scope:**
- Installing the GitHub Actions runner binary (still one-time GitHub UI)
- `METRICS_ENDPOINT` UI (listed on BACKLOG as follow-up)
- Changing default unattended permission mode away from `bypassPermissions`

## Approach

- Engine repo for CD vars/runners: prefs `ENGINE_GITHUB_REPO` (default `dentroio/agentic-factory`), editable on the page
- Reuse `_get_repo_variable` / `_set_repo_variable`
- Harness keys allowlisted in `product_setup` / draft_server: `AGENT_PERMISSION_MODE`, `AGENT_TOOL_ALLOWLIST`, `GEMINI_YOLO`, `CURSOR_TRUST`, `USAGE_BUDGET_USD_WEEK`, `ENGINE_GITHUB_REPO`
- After prefs save, UI prompts `make agent-stop && make agent-start` (or Agents start/stop)

## Acceptance Criteria

- [ ] Settings hub shows **Deploy & Harness**
- [ ] Page shows CD enabled state + runner list for engine repo
- [ ] Toggle persists `FACTORY_CD_ENABLED` as Actions variable on engine repo
- [ ] Harness form writes prefs; GET reflects current values
- [ ] No requirement to hand-edit `.env` / workflow files for these knobs
- [ ] Tests for prefs allowlist + orchestrator CD helpers
- [ ] BACKLOG.md tracks remaining operator steps
- [ ] `make ci-local` passes

## Verification Steps

```bash
# UI
open http://localhost:8099/settings/deploy-harness
# Toggle CD off/on; save harness budget; confirm prefs file updated:
grep USAGE_BUDGET_USD_WEEK ~/.config/factory-agent/prefs
make ci-local
```

---

## Execution

**Branch:** `wo/1094-factory-cd` (ships with WO-1094) or `wo/1095-deploy-harness-settings`
**Risk tier:** P2
**PR title:** `feat(status-site): WO-1095 — Deploy & Harness settings UI`
**Auto-merge:** yes (after human UI verify), or with WO-1094 if combined P1

**PM docs:** PROGRESS, CAPABILITY_STATUS, BACKLOG.md

### UI Verification

1. Open `http://localhost:8099/settings` — see **Deploy & Harness** card
2. Open Deploy & Harness — engine repo field, CD toggle, runner table, harness form
3. Save harness budget `25` — expected: success toast; prefs contain `USAGE_BUDGET_USD_WEEK=25`
4. Toggle CD — expected: GitHub variable updates (or clear error if token lacks `variables` permission)
5. No DevTools console errors
