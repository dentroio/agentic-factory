---
name: status-site-triple-status-mapping
description: status-site's _apply_live_status has three parallel status-mapping blocks (pr_wo_map, branch_wo_map, dispatch_map fallback) that must each handle agent_status values like retry_queued separately
metadata:
  type: project
---

In services/status-site/main.py, `_apply_live_status` determines a WO's displayed status from three separate code paths depending on what evidence exists: an open PR (pr_wo_map), a live branch (branch_wo_map), or just a bare dispatch entry with neither (dispatch_map fallback). Each path has its own status-mapping logic, and each defaults unmatched agent_status values to "In Progress". This same retry_queued bug was fixed three separate times (PRs before #175) because a fix applied to one map was not propagated to the others.

**Why:** The three code paths look similar but are independent branches — fixing the pr_wo_map case does not fix the branch_wo_map or dispatch_map cases, since each has its own if/elif chain with its own catch-all "else: In Progress".

**How to apply:** When adding/fixing an agent_status handling case (e.g. retry_queued, awaiting_human, gate-