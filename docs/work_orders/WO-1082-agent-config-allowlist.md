# WO-1082 — Allowlist keys on PUT /api/config

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1081
**Status:** 🟡 In Progress

---

## Background

AF-28 remainder: `put_agent_config` merges a raw JSON body into `agent_config.json`. Unknown keys, unbounded `timeout`, and arbitrary `preferred` / reviewer backends all persist. The runner reads this live (`preferred` selects a backend; reviewer names select CLIs).

Do **not** start the factory or unpause.

## What to Build

1. `agent_config_policy.apply_agent_config_updates` — known keys, backends, reviewer slots, timeout range, hostname-safe name.
2. `put_agent_config` uses it and returns 400 on rejection.
3. File write uses `atomic_write_json`.
4. Unit tests. Do not persist a live config change except via rejected probes.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — `put_agent_config` body and one import
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner
- `automation_model` stays on `/api/settings/automation-model`, not this PUT

## Acceptance Criteria

- [ ] Unknown keys (including `automation_model`) return 400 and are not stored
- [ ] `preferred` / reviewer backends outside claude/cursor/codex/gemini return 400
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/agent_config_policy.py` | Allowlist + validation |
| Modify | `services/orchestrator/orchestrator.py` | `put_agent_config` uses the policy |
| Create | `tests/unit/test_agent_config_allowlist.py` | Guards |
| Create | `docs/work_orders/WO-1082-agent-config-allowlist.md` | This spec |
| Modify | `docs/project_management/PROGRESS.md` | 1081 complete, 1082 in progress |

## Execution

- **Branch:** `wo/1082-agent-config-allowlist`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1082 — allowlist keys on PUT /api/config`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1081
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on. `PUT /api/config` with `{"not_a_key":"x"}` returns 400. Do not save a new preferred backend on the live factory.
