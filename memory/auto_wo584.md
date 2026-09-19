---
name: orchestrator-held-wo-blocking
description: Held/occupied WOs must never block the orchestrator queue — always exclude them from deps, advisor edges, and PM dispatch
metadata:
  type: project
---

The orchestrator's `_held_wos` set can silently stall the entire dispatch queue if a held/occupied WO is left as a dependency, advisor-edge target, or active PM direct-dispatch target. This happened for real: WO-588 being held (with an open PR) parked `/api/next` for days and blocked WO-584–589 behind it.

**Why:** Held WOs are expected to eventually clear (PR merge, claim completion), but nothing was proactively re-checking or bypassing them — deps (`_effective_depends`), conflict-advisor edges (`_apply_advisor_edge`), and PM dispatch (`_pm_dispatch` in `get_next`) all treated a held WO as a normal blocking dependency, causing indefinite stalls instead of graceful skips.

**How to apply:** When adding any new mechanism that creates a WO dependency, ordering constraint, or exclusive dispatch lock, always check `wo_id in _held_wos` and skip/clear rather than block. Also: `_is_ready` only recognized `📋 Ready`/`📋 Open` text — other emoji-prefixed "open" statuses (e.g. `🔲 Open`) were silently treated as not-ready; status checks should route through `classify_wo_status()` rather than hardcoded emoji/string prefixes.