# WO-1042 — Destructive Action Corroboration Guard + Override Tombstone

**Created:** 2026-07-22
**Priority:** P1
**Effort:** M
**Services:** orchestrator, intelligence
**Depends on:** WO-1041
**Status:** Open

---

## Background

Two failure classes observed July 22, 2026:

**1. Destructive actions ride on a single inferred signal.** The reconciler in `orchestrator.py` auto-completes a dispatch entry and triggers downstream cleanup on a title-only WO regex match against merged PRs. A PR titled "Fix regression from WO-410" merging with no `wo/410-` branch causes WO-410 to be marked complete — and any open WO-410 PR auto-closed. No corroboration required.

**2. Manual overrides don't survive the next poll cycle.** Deleting a ghost dispatch entry via API is undone within 300 seconds by the reconciler (which sees the merged PR scan and re-creates the stub). There is no tombstone. The human must fight the reconciler indefinitely.

Related: `_find_ghost_entries` in `intelligence.py` uses a 3-hour window and sets `status = "ghost"` immediately, which is irreversible within the same orchestrator session. A WO whose agent heartbeat stalled during a long CI run gets incorrectly cleared.

## What to Build

### 1. Corroboration gate on auto-complete

After WO-1041 lands, `resolve_wo_for_pr()` tags each resolution with its source (`branch` or `title`). Only auto-complete when source is `branch`:

```python
wo_num, source = resolve_wo_for_pr_with_source(pr)
if wo_num and source == "branch":
    # safe to auto-complete
elif wo_num and source == "title":
    # log as informational, do not auto-complete
```

### 2. Human override tombstone

Add `_overrides` dict to dispatch state (persisted in `dispatch_state.json`):

```json
{
  "_overrides": {
    "WO-410": { "action": "no-auto-complete", "set_by": "human", "set_at": "2026-07-22T..." }
  }
}
```

New API endpoints:

```
POST /api/wos/{wo_id}/override   body: {"action": "no-auto-complete"}
DELETE /api/wos/{wo_id}/override
GET  /api/wos/{wo_id}/override   (returns current override or 404)
```

Reconciler and ghost cleanup both check `_overrides` before acting:

```python
if _overrides.get(wo_id, {}).get("action") == "no-auto-complete":
    continue
```

### 3. Advisory ghost cleanup (downgrade from destructive to informational)

Change `_find_ghost_entries` / ghost cleanup to:

1. Set `ghost_warning: true` flag on the dispatch entry (non-destructive)
2. Post a thread comment: "⚠️ No active branch found for {wo_id} — may be stale. Human review recommended."
3. Do NOT change `status` on first detection

Only set `status = "ghost"` after `ghost_warning` has been present for >24h with no heartbeat.

### 4. Attribution on automated GitHub actions

Every automated comment or state change posted to GitHub must include a component + correlation ID:

```
🤖 Auto-completed by **reconciler** · run `a3f7b291`
```

Components: `reconciler`, `intelligence-loop`, `watchdog`, `reviewer`. Correlation ID: first 8 hex chars of `uuid4()` generated at start of each pass, logged to the thread store.

## Acceptance Criteria

- [ ] Auto-complete never fires when WO was resolved from title only (verified with test)
- [ ] `POST /api/wos/{wo_id}/override` creates tombstone; reconciler skips the WO
- [ ] `DELETE /api/wos/{wo_id}/override` removes tombstone; reconciler resumes normal behavior
- [ ] Override tombstone persists across orchestrator restart
- [ ] Ghost detection sets `ghost_warning` flag and posts comment; status unchanged on first pass
- [ ] Status only becomes `ghost` after 24h with `ghost_warning` set and no heartbeat
- [ ] All automated GitHub comments include component name + correlation ID
- [ ] Unit tests: title-only skipped, override respected, ghost downgrade, attribution present

## Files

- `services/orchestrator/orchestrator.py` — corroboration gate, override API, attribution
- `services/orchestrator/intelligence.py` — advisory ghost, attribution
- `services/orchestrator/wo_resolver.py` — add `resolve_wo_for_pr_with_source()`
- `services/orchestrator/tests/test_guard.py` — new
