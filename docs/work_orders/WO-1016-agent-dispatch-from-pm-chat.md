# WO-1016 — Agent Dispatch from PM Chat

**Status:** ✅ Done
**Priority:** P1
**Effort:** M
**Services:** orchestrator
**Depends on:** WO-1015

---

## Problem

The PM chat can advise on which WO to run next but cannot actually start it. When
the user says "start WO-185 with Cursor" the PM responds but nothing happens —
the agent runner keeps polling and the WO stays unstarted. The loop is open.

---

## What to Build

### Action tag in PM system prompt

Add `[DISPATCH:WO-NNN:backend]` to the list of action tags the PM can emit:

```
[DISPATCH:WO-185:cursor]   — claim WO-185 and dispatch to Cursor agent
[DISPATCH:WO-185:claude]   — claim WO-185 and dispatch to Claude agent
```

The PM emits this tag at the end of its response when the user confirms they
want to start a WO.

### Orchestrator — parse and execute DISPATCH tags

In `pm_chat()`, extend the action tag parser to handle `[DISPATCH:WO-NNN:backend]`:

1. Call `POST /api/claim` to mark the WO as claimed in `_dispatch_state`
2. If `AGENT_RUNNER_URL` is reachable, call `POST {AGENT_RUNNER_URL}/dispatch` with
   `{wo: "WO-NNN", backend: "cursor"}` to wake the runner immediately
3. If runner is offline, the WO sits claimed in state and the runner picks it up
   on its next poll cycle
4. Append a confirmation line to the reply: "✅ WO-185 dispatched to Cursor"

### New agent runner endpoint

Add `POST /dispatch` to `agent_runner.py`:
```json
{"wo": "WO-185", "backend": "cursor"}
```
Interrupts the current poll sleep and immediately processes the specified WO.

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | PM emits `[DISPATCH:WO-NNN:backend]` when user confirms a WO start |
| 2 | Orchestrator parses tag, claims WO, pings runner |
| 3 | Runner receives dispatch, starts WO within 10 seconds |
| 4 | PM reply includes "✅ WO-NNN dispatched to {backend}" |
| 5 | If runner is offline, WO is claimed and picked up on next poll |
| 6 | Works from both Slack bot and browser PM chat |
