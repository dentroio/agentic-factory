# WO-1092 — Unique draft ports + one-click product remount

**Created:** 2026-09-06
**Priority:** P2
**Effort:** S
**Services:** agent-runner, orchestrator, status-site, docs
**Depends on:** WO-1091
**Status:** ✅ Done

---

## Problem

1. **Port clash:** Only the Claude LaunchAgent sets `DRAFT_PORT` (8102). Cursor / Codex / Gemini (and a stale secondary agent) all default to **8101**, so one process wins and the others fail with `Address already in use`. The orchestrator then talks to whatever stale draft server still holds 8101 — which is how Get Started saw `{"detail":"Not Found"}` for `/api/product`.

2. **Manual remount:** After Get Started / Auth changes `LOCAL_REPO_PATH`, Docker still mounts the old path until the operator runs `make restart`. That breaks the UI-first loop.

## What to Build

1. **Unique draft ports** — Align `draft_server._AGENT_META` `extra_env.DRAFT_PORT` with `health_agent.RUNNER_PORTS` (cursor 8101, claude 8102, codex 8103, gemini 8104). Keep orchestrator candidate list in sync. On bind failure, log a clear remediation hint (which port, `lsof` / stop the other agent).

2. **One-click remount** — Host `POST /api/product/remount` (bearer-gated) runs `scripts/compose-with-env.sh up -d --force-recreate` from the engine root (no image rebuild). Orchestrator proxies. Get Started + Auth show a **Remount Docker** action when `restart_required` (still keep the manual `make restart` hint as fallback).

3. **Tests + docs** — Unit guards for port map parity; doctor/docs note remount button.

## Out of scope

- Full `make restart` (image rebuild) from the UI
- Linux/systemd remount parity
- Killing foreign processes that hold draft ports automatically
- Multi-repo local path mounts

## Do NOT change

- Bearer gate on draft-server routes
- Live Clarion legacy profile behavior

## Acceptance Criteria

- [x] Cursor / Claude / Codex / Gemini LaunchAgent meta each have distinct `DRAFT_PORT` values matching `health_agent.RUNNER_PORTS`
- [x] Unit test fails if `_AGENT_META` ports drift from `RUNNER_PORTS`
- [x] Draft bind failure logs port + remediation (no silent thread death only)
- [x] `POST /api/product/remount` is bearer-gated on draft server and proxied by orchestrator
- [x] Get Started / Auth expose a remount control when path changed
- [x] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `docs/work_orders/WO-1092-draft-ports-and-remount.md` | This spec |
| Modify | `services/agent-runner/draft_server.py` | Ports + remount route + bind logging |
| Modify | `services/agent-runner/product_setup.py` | `remount_compose()` |
| Modify | `services/orchestrator/orchestrator.py` | Proxy remount |
| Modify | `services/status-site/main.py` | Remount POST handler |
| Modify | `services/status-site/templates/settings_get_started.html` | Remount button |
| Modify | `services/status-site/templates/settings_authentication.html` | Remount button |
| Create | `tests/unit/test_draft_ports.py` | Port parity guard |
| Modify | `tests/unit/test_product_setup.py` | Remount unit test (mocked subprocess) |
| Modify | `docs/wiki/Getting-Started.md` | Remount via UI |

## Execution

- **Branch:** `wo/1092-draft-ports-and-remount`
- **Risk tier:** P2
- **Services:** agent-runner, orchestrator, status-site
- **PR title:** `feat(adoption): WO-1092 — unique draft ports and one-click remount`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1091
- **User verification required:** Yes — confirm `/api/product` stays up with multiple agents; Remount Docker button recreates compose
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md
