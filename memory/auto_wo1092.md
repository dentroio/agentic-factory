---
name: draft-server-per-agent-ports
description: Each agent backend (claude/cursor/codex/gemini) must have a unique DRAFT_PORT; ports are duplicated in draft_server.py and health_agent.py and must stay in sync.
metadata:
  type: project
---

Each backend's draft server binds to a distinct port to avoid multi-agent collisions: claude=8102, cursor=8101, codex=8103, gemini=8104. These ports are set via `extra_env["DRAFT_PORT"]` per-agent in `services/agent-runner/draft_server.py` (`_AGENT_META`), but the *canonical/expected* mapping also lives separately in `services/agent-runner/health_agent.py` (`RUNNER_PORTS`). There's no shared source of truth — the two dicts must be kept manually in sync.

**Why:** Before this PR all backends defaulted to shared port 8101, so running multiple agents locally caused silent bind collisions (only the first agent's draft server would actually be listening; others failed silently or clobbered state). `test_draft_ports.py` now asserts uniqueness and cross-file consistency, but only for these two files.

**How to apply:** When adding a new agent backend or changing draft server ports, update `_AGENT_META` in `draft_server.py` AND `RUNNER_PORTS` in `health_agent.py` together, and run `tests/unit/test_draft_ports.py` to catch drift. Also note: a bind failure now logs remediation hints (`lsof -nP -