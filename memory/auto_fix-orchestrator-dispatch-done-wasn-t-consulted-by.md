---
name: orchestrator-dispatch-done-precedence
description: dispatch_done (from /api/complete) must take precedence over spec file status text in every WO status computation in orchestrator.py, not just done_wos
metadata:
  type: project
---

In `services/orchestrator/orchestrator.py`'s `poll()`, WO completion status is derived from two sources: the spec file's status text (rewritten asynchronously) and `dispatch_done` (the orchestrator's own in-memory `_dispatch_state`, updated immediately via `/api/complete`). There's a window where a WO is done per `dispatch_state` but the spec file hasn't caught up yet.

`done_wos` already OR'd in `dispatch_done`, but `open_wos` and `_plan_overlay` were computed separately right next to it and only checked spec text — so a WO could be simultaneously in `done_wos` and still re-offered to a runner via `/api/next` (fed by `_plan_overlay`). This was found via an "audit" pass, not by symptom/bug report — it's the kind of inconsistency that only shows up in a live race window, not in tests.

**Why:** Any new set/overlay computed from `specs` in this poll loop that determines whether a WO is dispatchable or open must independently exclude `dispatch_done`, since the spec file is not a reliable real-time source of truth for completion.

**How to apply:** When ad