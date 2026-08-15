---
name: wo-detail-page-must-use-apply-live-status-fallback
description: wo_detail() route must reconcile via apply_live_status() before 404ing, not just look for a spec file
metadata:
  type: project
---

In services/status-site/main.py, the WO detail page (`/wo/{number}`) and the board pages (Overview/PM/Factory) used to use two different code paths to determine a WO's existence/status: the boards call `apply_live_status()` which synthesizes a placeholder WO from branch/PR/dispatch signals even when no spec file was ever committed, but `wo_detail()` only looked for a spec file and 404'd immediately if none existed. This meant a WO visibly "stalled" (or running/awaiting-review) on the board with a real pushed branch would 404 with zero context when clicked into.

**Why:** Any board card that appears via `apply_live_status()`'s placeholder synthesis (branch/PR/dispatch exists, no spec file) implies a live WO the detail page must also be able to render — otherwise the detail page is strictly less informative than the card that linked to it.

**How to apply:** When adding/modifying WO detail or single-item view routes, don't treat "no committed spec file" as equivalent to "WO doesn't exist" — run the same `apply_live_status()` reconciliation (branches, open PRs, dispatch, merged PRs) used by the boards first, and only fall back to a bare 404 if that also yields nothing. Also, `_load_dispatch()` is now a single module-level function (services/status-