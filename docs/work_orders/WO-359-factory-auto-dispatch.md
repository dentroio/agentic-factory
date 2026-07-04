# WO-359 — Factory Auto-Dispatch

**Status:** ✅ Complete
**Priority:** P1
**Repo:** `dentroio/agentic-factory`
**Estimated effort:** S (3–4 hours)
**Depends on:** WO-358 (plan store + `/api/plan/next` endpoint)

---

## Background

WO-358 built `/api/plan/next` — the factory now knows what to work on next. WO-359 closes the loop: when the orchestrator detects that no WO is in progress and the queue is non-empty, it automatically dispatches the next WO to an agent.

## What Needs to Happen

### dispatch_next_wo() in orchestrator
```python
async def dispatch_next_wo(plan_next: dict | None, active_wos: set) -> None:
    if plan_next is None or plan_next["wo"] in active_wos:
        return
    wo_id = plan_next["wo"]
    # Write /data/dispatch.json
    dispatch = {"wo": wo_id, "dispatched_at": utcnow(), "status": "pending"}
    DISPATCH_PATH.write_text(json.dumps(dispatch))
```

### Host-side listener
`scripts/factory_dispatch_listener.sh` — polls `/data/dispatch.json`, picks up pending dispatches, launches `make wo-start NNN=NNN SLUG=slug` in the appropriate worktree, marks dispatch as `running`.

### Stall detection
If a WO has been `in_progress` for more than `STALL_HOURS` (default 4) with no new commits on its branch, the orchestrator comments on the WO's GitHub issue: "WO-NNN has been in progress for X hours with no commits — possible stall."

### Safety gate
`AUTO_DISPATCH=false` by default. Set to `true` in `.env` to enable. Dry-run mode logs what would be dispatched without writing the file.

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | With `AUTO_DISPATCH=true`, orchestrator writes `/data/dispatch.json` when queue is non-empty and no WO is active |
| 2 | Listener script picks up dispatch and launches `make wo-start` |
| 3 | Stall detection fires after `STALL_HOURS` with no commits |
| 4 | `AUTO_DISPATCH=false` (default) — orchestrator logs intent but does not dispatch |

## Key Files to Create/Modify

| File | Change |
|------|--------|
| `services/orchestrator/orchestrator.py` | Add `dispatch_next_wo()` + stall detection |
| `scripts/factory_dispatch_listener.sh` | New — host-side listener |
| `.env.example` | Add `AUTO_DISPATCH=false`, `STALL_HOURS=4` |
