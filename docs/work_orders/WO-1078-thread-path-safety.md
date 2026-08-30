# WO-1078 — Reject path traversal in thread storage (AF-28)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1077
**Status:** ✅ Complete

---

## Background

AF-28: `get_thread_image` joins `DATA_DIR / "threads" / "images" / wo / filename` from two unvalidated path parameters. `wo=".."` lands in `/data/threads/<filename>`. The same `wo` reaches `mkdir` and `thread.save_thread`'s `{wo_id}.json` write.

Uvicorn often percent-decodes before routing, so `%2f` may not smuggle slashes — that is incidental. `..` as a single segment is still a real join.

Do **not** start the factory or unpause.

## What to Build

1. `require_wo_id` / `require_image_filename` / `contained_path` in `thread.py`.
2. `load_thread` / `save_thread` use them.
3. Thread HTTP routes return 400 on unsafe segments.
4. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — thread API block only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] `wo=".."` and `filename=".."` cannot escape the images/threads roots
- [ ] Thread JSON writes are confined to `THREADS_DIR / WO-N.json`
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/thread.py` | Allowlist + contained join |
| Modify | `services/orchestrator/orchestrator.py` | 400 on unsafe thread routes |
| Create | `tests/unit/test_thread_path_safety.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1077 complete, 1078 in progress |

## Execution

- **Branch:** `wo/1078-thread-path-safety`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1078 — reject path traversal in thread storage`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1077
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
