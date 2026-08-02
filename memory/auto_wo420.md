---
name: file-locks-need-stale-holder-detection
description: Any file-based lock in this codebase must check if the recorded holder PID is still alive before waiting out the timeout
metadata:
  type: project
---

File locks used to serialize work across processes (e.g. `run_ci()`'s CI lock in `services/agent-runner/quality_gate.py`) are only released by the holder's own `finally:` block. If the holder is killed mid-run (daemon restart via `launchctl