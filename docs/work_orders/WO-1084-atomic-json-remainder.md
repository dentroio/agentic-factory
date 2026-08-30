# WO-1084 — Atomic JSON writes for remaining /data state (AF-27 remainder)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1083
**Status:** ✅ Complete

---

## Background

WO-1065 made dispatch, hold, validations, and threads atomic. Secrets and agent config followed. Remaining `/data` JSON still uses bare `write_text(json.dumps(...))`. A crash mid-write leaves truncated JSON; loaders then fall back to `{}` / `[]` and drop overrides, reservations, PM memory, usage, and Slack history.

Do **not** start the factory, the runner, or unpause.

Out of scope: `PLAN.json` write-back into the product git tree; agent-runner / status-site / pr-watchdog JSON (not orchestrator `/data`).

## What to Build

1. Remaining orchestrator `/data` JSON saves use `dispatch_control.atomic_write_json`.
2. Same for intelligence acted-on and Slack bot state.
3. Unit tests. Live verify pause after deploy.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — save helpers and usage/output writes only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] Overrides, reserved WOs, PM memory, intelligence state, orchestrator output, usage, and Anthropic usage use `atomic_write_json`
- [ ] Intelligence acted-on and Slack state use `atomic_write_json`
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/orchestrator.py` | Remaining `/data` JSON saves |
| Modify | `services/orchestrator/intelligence.py` | Acted-on save |
| Modify | `services/orchestrator/slack_bot.py` | Slack state save |
| Modify | `tests/unit/test_dispatch_control.py` | Source guards |
| Create | `docs/work_orders/WO-1084-atomic-json-remainder.md` | This spec |
| Modify | `docs/project_management/PROGRESS.md` | 1083 complete, 1084 in progress |

## Execution

- **Branch:** `wo/1084-atomic-json-remainder`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1084 — atomic JSON writes for remaining /data state`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1083
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on. Do not start the runner.
