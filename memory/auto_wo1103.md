---
name: orchestrator-queue-is-not-repo-scoped
description: The dispatch queue table has no repo column, so any factory instance can accidentally enqueue/claim WOs belonging to another repo (e.g. engine WOs on a product factory) unless explicitly gated.
metadata:
  type: project
---

The orchestrator's `queue` DB table stores only a WO id/number, with no repo/product association. Historically this let engine WOs (dentroio/agentic-factory work orders) leak into a product factory's (e.g. Clarion) queue and get claimed/dispatched against the wrong worktree, purely because the WO number existed in *some* spec cache or on disk somewhere.

The fix (`product_wo_gate.py`) enforces eligibility by checking that a spec file exists under this factory's `LOCAL_REPO_MOUNT/WO_PATH` on disk, OR that the specs cache entry's `repo` field matches this factory's `GITHUB_REPO` — not just that the WO number exists anywhere.

**Why:** The queue schema itself provides no protection against cross-repo WO contamination; correctness depends entirely on gating logic applied at every entry point (enqueue, claim, `/api/next` candidate filtering) plus periodic purge (startup + poll loop) to clean up anything that slipped in before the gate existed.

**How to apply:** When adding any new way to add/claim/dispatch WOs (new endpoint, bulk import, migration script, etc.), always route through `product_has_spec()` / `_