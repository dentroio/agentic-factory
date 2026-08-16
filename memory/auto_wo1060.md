---
name: dispatch-attempt-counts-persist-separately
description: DELETE /api/dispatch does not reset WO retry attempt counts — they live in a separate side file cleared only via /reset
metadata:
  type: project
---

`attempt_count` for a WO is no longer solely derived from `_dispatch_state` (which DELETE /api/dispatch clears). It is also persisted in `ATTEMPTS_PATH` (data/attempt_counts.json) via `dispatch_control.load_attempt_counts`/`save_attempt_counts`, and `claim_wo` takes `max(persisted, dispatch_state_count)` via `recorded_attempts()`. Only the explicit `/api/dispatch/reset/{wo_id}` endpoint clears the persisted count (`clear_attempt`).

**Why:** Before this change, deleting dispatch state (e.g. to unstick a WO) silently reset the retry ceiling (MAX_RETRY_ATTEMPTS), letting a WO retry indefinitely by bypassing the max-retry guard. This was a discovered loophole (AF-21).

**How to apply:** If touching retry/attempt logic or dispatch state deletion, remember the attempt count has two sources of truth that must be kept in sync — don't assume clearing `_dispatch_state`/DB row resets attempts. Any new "clear WO state" endpoint should decide explicitly whether it also calls `dispatch_control.clear_attempt` + `save_attempt_counts`, or it will inherit the