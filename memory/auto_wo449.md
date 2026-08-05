---
name: orchestrator-approval-state-decoupled-from-dispatch-state
description: Human WO approval must be tracked independently of _dispatch_state, which gets wiped/reset on claim/release/retry cycles
metadata:
  type: project
---

In services/orchestrator/orchestrator.py, `_dispatch_state[wo_id]` is transient and gets popped/reset by claim_wo, release_dispatch, and retry_dispatch as part of normal churn (by design, so stale statuses don't leak into new work attempts). This means `_dispatch_state[wo_id]["status"] == "approved"` is NOT a reliable signal that a human approved a WO — it can be wiped by an unrelated transient failure (e.g. container rebuild retry), silently forcing re-approval of the same risk decision.

A separate session-scoped set, `_wo_ever_approved`, now tracks approval independent of dispatch churn. `approve_wo()` populates it; the approval gate in `claim_wo()` checks it in addition to `_dispatch_state` status.

**Why:** Approval represents a human risk decision tied to the WO identity, not to a specific dispatch/claim attempt. Dispatch state churn is an implementation detail that shouldn't affect it.

**How to apply:** If you add new code paths that reset, cl