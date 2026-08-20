---
name: orchestrator-silent-stall-detection
description: Orchestrator dispatch queue can silently stall (all WOs held, nothing active) for hours with no alert — new health/stall detectors must mirror /api/next's exact filter and use one-alert-per-episode in-memory state.
metadata:
  type: project
---

The orchestrator previously had no alerting for the dispatch queue being non-empty but fully held (all queued WOs held, `wos_active=0`) — runners just poll `/api/next` forever getting "queue empty or all candidates claimed/blocked" with nothing surfaced to a human. This ran silently for ~36h in production before being noticed. The stuck-WO auto-hold path existed but only logged