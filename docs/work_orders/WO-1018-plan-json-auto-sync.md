# WO-1018 — PLAN.json Auto-Sync from WO Spec Files

**Status:** ✅ Done
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-1004

---

## Problem

The clarion PLAN.json queue only has 31 WOs, all marked done. WOs with status
"Ready", "Open", or "Planned" in their spec files are invisible to the
orchestrator — the queue is empty and the PM says "nothing to do" even when
work exists. PLAN.json is maintained manually and has drifted far behind
the actual spec files.

---

## What to Build

### Orchestrator poll: reconcile spec statuses into PLAN.json

During the existing `poll()` cycle, after loading the plan:

1. Read all WO spec files from `LOCAL_REPO_MOUNT` (already done by `_read_local_wo_specs()`)
2. For each spec with status "Ready", "Open", or "Planned" that is **not** in
   PLAN.json `queue` or `deferred`:
   - Add it to an in-memory overlay with `status: "open"` and metadata from
     the spec (priority, effort, title)
3. Merge the overlay into `_plan_state["queue"]` so `next_wo()` and PM context
     see all actionable WOs — without writing back to the file (PLAN.json
     remains human-controlled; the overlay is runtime-only)

### `/api/status` surface overlay count

Add `"overlay_wos": N` to the status response so the dashboard and PM can
report "31 done in PLAN.json + 12 ready from specs".

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | WO-185, WO-186, WO-187 appear in `/api/next` candidates after poll |
| 2 | PM chat "what's next?" returns spec-file WOs, not just PLAN.json ones |
| 3 | PLAN.json file is never modified by this process |
| 4 | Overlay WOs appear in factory dashboard queue panel |
| 5 | `/api/status` includes `overlay_wos` count |
