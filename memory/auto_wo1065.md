---
name: orchestrator-atomic-json-writes
description: All orchestrator JSON state files must be written via dispatch_control.atomic_write_json, not path.write_text
metadata:
  type: project
---

Orchestrator state files (dispatch state, hold list, validations, attempt counts, thread JSON) are written using `dispatch_control.atomic_write_json(path, payload)` — writes to a `.tmp` sibling then `replace()`s — instead of `path.write_text(json.dumps(...))`. This prevents truncated/corrupt state if the process crashes mid-write, since these files represent in-flight factory claims that other processes read directly off the volume.

**Why:** A direct `write_text` can leave a partially-written JSON file if interrupted, corrupting shared state read by other processes/containers.

**How to apply:** When adding any new persisted JSON state in `services/orchestrator/` (dispatch, hold, validations, threads, attempt counts, or future state), use `dispatch_control.atomic_write_json()` rather than raw `write_text`. Note there's a regression test (`tests/unit/test_dispatch_control.py`) that greps orchestrator/thread source for `.write_text(json.d