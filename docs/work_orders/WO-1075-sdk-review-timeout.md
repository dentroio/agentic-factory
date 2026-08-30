# WO-1075 — Bound the parallel SDK review path (AF-24)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** agent-runner, docs
**Depends on:** WO-1074
**Status:** ✅ Complete

---

## Background

WO-1069 bounded every runner `communicate()` and the sequential CLI `ask()` path (120s). The parallel Anthropic SDK review path still has no timeout: `_run_sdk_reviewer` → `to_thread` → `client.messages.create` with the SDK default (~10 minutes, or hang). A stuck HTTP call parks `run_wo` with no heartbeat.

Do **not** start the factory, the runner, or unpause.

## What to Build

1. Pass an explicit timeout into the Anthropic client (same 120s budget as CLI `ask()`).
2. Wrap the `to_thread` await in `asyncio.wait_for` so a hung thread cannot stall the chain forever.
3. Unit test that both bounds are present.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Do not start the runner to verify
- Do not recreate Vault
- Sequential CLI path already uses `wait_for(..., timeout=120)` — keep the budgets aligned

## Acceptance Criteria

- [ ] SDK reviewer constructs Anthropic with an explicit timeout
- [ ] `_run_sdk_reviewer` awaits `to_thread` under `wait_for`
- [ ] Factory stays paused; runner stays down
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/agent-runner/review_chain.py` | Client timeout + wait_for |
| Modify | `tests/unit/test_subprocess_timeouts.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1074 complete, 1075 in progress |

## Execution

- **Branch:** `wo/1075-sdk-review-timeout`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(runner): WO-1075 — timeout the parallel SDK review path`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1074
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Do not start the runner. Confirm pause is still on and `/api/next` still drains.
