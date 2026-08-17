# WO-1083 — Pause must refuse runner start

**Created:** 2026-08-16
**Priority:** P0
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1082
**Status:** 🟡 In Progress

---

## Background

Pause blocks `/api/claim` (423) but `POST /api/runner/agents/{name}/start` still proxies to the draft server. Live, that is 503 only because port 8101 is closed. If the runner is up, pause does not stop LaunchAgent bootstrap. `PUT /api/runner/agents/{name}` accepts any JSON, including `start: true`, and unknown `name` values are forwarded.

Do **not** start the factory, the runner, or unpause.

## What to Build

1. Allowlist agent names (`claude` / `cursor` / `codex` / `gemini`) and configure keys (`api_key`, `domain_filter`, `start`).
2. `POST .../start` and `PUT` with `start: true` call `_refuse_if_paused()` before contacting the runner.
3. Invalid JSON on configure is 400, not an empty body.
4. Unit tests. Live verify with 423 — do not start the runner.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — runner-agent routes only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner
- Stop/delete stay allowed so a drain can finish

## Acceptance Criteria

- [ ] `POST /api/runner/agents/claude/start` returns 423 while paused (not 503)
- [ ] `PUT` with `start: true` returns 423 while paused
- [ ] Unknown agent names and configure keys return 400
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/runner_agents.py` | Allowlist |
| Modify | `services/orchestrator/orchestrator.py` | Pause gate + allowlist |
| Create | `tests/unit/test_pause_blocks_runner_start.py` | Guards |
| Create | `docs/work_orders/WO-1083-pause-blocks-runner-start.md` | This spec |
| Modify | `docs/project_management/PROGRESS.md` | 1082 complete, 1083 in progress |

## Execution

- **Branch:** `wo/1083-pause-blocks-runner-start`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1083 — pause must refuse runner start`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1082
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on. `POST /api/runner/agents/claude/start` returns 423. Do not start the runner.
