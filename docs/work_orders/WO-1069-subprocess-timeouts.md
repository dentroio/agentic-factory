# WO-1069 — Bound runner subprocess calls (AF-24)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** agent-runner, docs
**Depends on:** WO-1068
**Status:** ✅ Complete

---

## Background

AF-24: `quality_gate._run` wraps `communicate()` in `asyncio.wait_for`. `runner.py`, `review_chain.py`, and the CLI backends do not. A hung `git push`, `gh pr create`, or `claude --print` parks `run_wo` forever with no heartbeat.

This WO adds one helper that times out and kills the child. It does **not** add a timeout to the parallel Anthropic SDK review path (follow-up).

Do **not** start the factory, the runner, or unpause.

## What to Build

1. `proc.communicate(proc, timeout)` — `wait_for` + kill + wait on timeout.
2. Every unbounded `communicate()` in the runner, review chain, quality gate, and CLI `ask()` paths goes through it.
3. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Do not start the runner to verify
- Do not recreate Vault
- Streaming `run()` loops stay unbounded — those are the WO itself

## Acceptance Criteria

- [ ] No bare `.communicate()` in runner/review_chain/quality_gate/backends except `proc.py`
- [ ] Timed-out children are killed
- [ ] Factory stays paused; runner stays down
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/agent-runner/proc.py` | Bounded communicate + kill |
| Modify | `services/agent-runner/runner.py` | git / wo_start / gh |
| Modify | `services/agent-runner/review_chain.py` | git diff / fetch |
| Modify | `services/agent-runner/quality_gate.py` | kill on timeout |
| Modify | `services/agent-runner/backends/*.py` | `ask()` |
| Create | `tests/unit/test_subprocess_timeouts.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1068 complete, 1069 in progress |

## Execution

- **Branch:** `wo/1069-subprocess-timeouts`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(runner): WO-1069 — bound subprocess communicate with kill-on-timeout`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1068
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Do not start the runner. After the change, confirm pause is still on and `/api/next` still drains.
