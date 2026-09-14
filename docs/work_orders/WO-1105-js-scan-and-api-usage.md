# WO-1105 — Harden JS/TS security scan + record API token usage

**Created:** 2026-09-14
**Priority:** P2
**Effort:** S
**Services:** agent-runner, docs
**Depends on:** WO-1093
**Status:** ✅ Complete (2026-09-14)

---

## Problem

Two open capability gaps remain (CD deferred):

1. JS/TS security scanning often falls back to a 6-pattern regex because
   `eslint-plugin-security` is not installed in the product worktree.
2. `/api/usage` only stores `len/4` token estimates even when the Anthropic SDK
   review harness already returns real `usage.input_tokens` / `output_tokens`.

## What to Build

1. Pin `eslint@8` + `eslint-plugin-security` via `npx --yes -p …`, expand rule
   set and JSX/TSX coverage, enrich regex fallback.
2. Capture Anthropic SDK usage from the parallel review harness and prefer it
   in `usage_tracker` (`usage_source: api|estimate`).
3. Update CAPABILITY_STATUS / BACKLOG / LLM-Harness notes.

## Out of scope

- Enabling CD / `FACTORY_CD_ENABLED`
- Exact billing for subscription CLI coding runs (providers do not expose usage)
- Setting operator `METRICS_ENDPOINT` / `USAGE_BUDGET_USD_WEEK` values

## Acceptance Criteria

- [ ] `run_js_security` installs eslint-plugin-security via npx when missing
- [ ] `.tsx` / `.jsx` included; regex fallback covers React XSS patterns
- [ ] SDK review path records `input_tokens` / `output_tokens` into usage
- [ ] `usage_source` is `api` when provider tokens present, else `estimate`
- [ ] Unit tests cover both paths; `make ci-local` passes

## Execution

- **Branch:** `wo/1105-js-scan-and-api-usage`
- **Risk tier:** P2 — auto-merge after human verify (no UI; agent-runner restart)
- **PR title:** `feat(agent-runner): WO-1105 — JS security scan + API usage`
- **PM docs:** PROGRESS.md, CAPABILITY_STATUS.md, BACKLOG.md

### Verification

1. `python3 -m pytest tests/unit/test_js_security_and_usage.py tests/unit/test_usage_tracker.py -q`
2. `make agent-stop && make agent-start` (or restart agent-runner)
3. Confirm no regression: next WO with JS changes runs eslint (or regex fallback with `scanner` field)
