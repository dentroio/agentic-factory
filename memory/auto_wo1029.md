---
name: stuck-detection-uses-last-seen-not-step-change
description: The stuck clock resets on heartbeat OR checkin — agents must call /heartbeat every ~5 min during long-running steps to avoid auto-hold
metadata:
  type: project
---

The orchestrator's stuck detection measures idle time from `last_seen`, not from step transitions. An agent can be actively working on the same step for hours (e.g., a long test run or compilation) and will be auto-held after 2× its priority threshold unless it explicitly calls `POST /api/wos/{wo_id}/heartbeat` to reset the clock.

**Why:** The design separates "is the agent alive?" (heartbeat) from "what is the agent doing?" (checkin/step). This means agents that only call checkin at step boundaries — which may be hours apart — will trigger stuck alerts even if they're working correctly.

**How to apply:** Any agent that performs work lasting longer than its WO's STUCK_THRESHOLD (P0: 4h, P1: 12h, P2: 24h, P3: 48h) without a step transition must call the heartbeat endpoint on a ~5 minute cadence during that work. Failing to do so will first set `stuck=True` on the dispatch entry, then auto-add the WO to `_held_wos` after 2× threshold, blocking further progress until a human un-holds it.