---
name: orchestrator-poll-cycle-loop-isolation
description: poll() sweep loops over dispatch/preflight state must re-read entries after any await and wrap per-item work in try/except
metadata:
  type: project
---

In `services/orchestrator/orchestrator.py`, `poll()` runs multiple sweeps (stale-claim sweep, preflight-retry sweep, auto-reconcile) over shared mutable dicts (`_dispatch_state`, `_preflight_held`) across `await` points (e.g. GitHub API lookups, `preflight_check`). Concurrent requests (DELETE /api/dispatch, checkin, reset) can remove or mutate a WO's entry mid-await, so code that captured a reference or did `state[wo_id]` before the await can KeyError and abort the *entire* poll cycle, silently starving all other WOs in that tick.

**Why:** A single unhandled exception partway through one of these loops previously killed the whole sweep for that cycle — not just the one WO that vanished.

**How to apply:** When adding/editing sweep logic here:
- Use `dispatch_control.live_claim(state, wo_id)` (or an equivalent re-fetch-and-validate-status helper) instead of trusting a dict entry captured before an `await`.
- Re-fetch entries from the source dict (e.g. `_preflight_held.get(wo_id)`, re-checking for `None`) after any `await` before mutating.
- Wrap each per-WO iteration body in its own `try/except Exception