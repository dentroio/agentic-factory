---
name: orchestrator-json-writes-must-be-atomic
description: All JSON state file writes in orchestrator must use dispatch_control.atomic_write_json, never Path.write_text
metadata:
  type: project
---

Any new persisted JSON state file under services/orchestrator (or intelligence.py, slack_bot.py) must be written via `dispatch_control.atomic_write_json(path, data)` instead of `path.write_text(json.dumps(...))`. Direct writes can leave truncated/corrupt JSON if the process crashes mid-write, which loaders then treat as empty/valid instead of erroring.

**Why:** A prior incident (WO-1084) found multiple state files (overrides, reserved_wos, pm_memory, intelligence_state, orchestrator output, usage logs, acted_on, slack_bot state) still using raw `write_text`, causing silent data loss on crash.

**How to apply:** When adding a new `_save_*()` function for JSON state in orchestrator/intelligence/slack_bot, import `dispatch_control` and call `dispatch_control.atomic_write_json(PATH, data)`. There's a regression test (`test_remaining_data_json_saves_use_atomic_write` in tests/unit/test_dispatch_control.py) that greps source files for `.write_text` on known path constants — add new path constants to that test's assertion list if introduced.