---
name: planned-wo-board-vs-dispatch-separation
description: The status-site board column and the orchestrator's dispatch eligibility are intentionally decoupled — merging 'planned' into 'open' for display does NOT affect which WOs agents pick up
metadata:
  type: project
---

The status-site board has no influence on WO dispatch. The orchestrator's `_is_ready()` check is the sole gatekeeper for whether an agent actually picks up a WO. Board column labels are purely cosmetic/informational.

**Why:** There was a hidden `planned` board column that the lifecycle section never rendered, silently swallowing 20+ backlog WOs from view. The fix collapses `planned` into `open` for display purposes. A future agent might worry this change accidentally makes Planned WOs dispatchable — it does not, because dispatch is enforced elsewhere.

**How to apply:** When modifying WO status mapping in `wo_parser.py` or the status site, do not conflate "visible on board" with "eligible for dispatch." If you need to gate dispatch on a status, change the orchestrator's `_is_ready()` check, not the board column mapping. Similarly, if WOs are mysteriously missing from the board, check whether their status maps to a column that is actually rendered in the lifecycle section.