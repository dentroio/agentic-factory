---
name: agent-runner-bounded-subprocess-communicate
description: All subprocess.communicate() calls in agent-runner must go through proc.communicate() with a timeout, never raw asyncio proc.communicate()
metadata:
  type: project
---

`services/agent-runner/proc.py` provides a `communicate(proc, timeout)` wrapper that kills the child process on timeout instead of hanging forever. A raw `await proc.communicate()` anywhere in agent-runner (runner.py, review_chain.py, quality_gate.py, backends/*.py) could hang `run_wo` indefinitely if a git/gh/CLI subprocess stalls (e.g. auth prompt, network hang, quota UI).

**Why:** Before this change, a single hung subprocess (git push, gh pr create, claude/codex/gemini ask()) would park the entire WO run forever with no timeout — a real production failure mode (WO-1069/AF-24). Named timeout constants live in `proc.py` (GIT=30s, GIT_PUSH=120s, GIT_FETCH=60s, WO_START=120s, GH=60s, ASK=120s) — reuse these rather than inventing new magic numbers.

**How to apply:** When adding any new subprocess call in agent-runner, use `from proc import communicate as _communicate` (plus the relevant timeout constant) instead of calling `proc.communicate()` directly. Wrap it in `try/except asyncio.TimeoutError` and handle gracefully (return a placeholder string,