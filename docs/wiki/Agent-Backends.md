---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-09-26
covers_wos:
  - WO-1008
  - WO-1053
  - WO-1082
  - WO-1092
doc_owner: factory-team
---

# Agent Backends

Backends execute Work Orders **against the product** (`GITHUB_REPO`), in a worktree under `LOCAL_REPO_PATH`. Enable what you use in **Settings → Agents → LLM Providers**.

## Execution backends

| Backend | Runs | You need |
|---------|------|----------|
| `claude` | Host CLI | Claude Pro/Max + logged-in `claude` |
| `cursor` | Host CLI | Cursor Pro + logged-in CLI |
| `codex` | Host CLI | OpenAI Codex subscription |
| `gemini` | Host CLI | Gemini Advanced + CLI |
| `claude-api` | Docker → Anthropic API | `ANTHROPIC_API_KEY` in Settings |

Subscription CLIs use **host** login cookies/tokens — Docker never mounts them. Each host backend runs its own draft server on a dedicated port — cursor `:8101`, claude `:8102`, codex `:8103`, gemini `:8104` — that bridges orchestrator → host CLI. Ports are unique per backend (WO-1092) so running multiple agents at once no longer causes one to silently fail with "address already in use." A bind failure now also logs which port collided and a remediation hint (check `lsof`, stop the conflicting agent).

Disable unused providers so dispatch never selects them. Preferred backend: **Settings → Agents** (also in `~/.config/factory-agent/prefs`).

`PUT /api/config` (the endpoint Settings → Agents writes to) validates every update against an allowlist: `preferred` and each reviewer slot must be one of `claude` / `cursor` / `codex` / `gemini` (plus `antares` for the security reviewer only), `timeout` must fall in a bounded range, and unknown keys are rejected with `400` rather than silently persisted. `automation_model` is not part of this endpoint — it's set via `/api/settings/automation-model`.

## Host runner vs API-only

| Mode | When |
|------|------|
| `make agent-install` / `agent-run` | Normal path for Claude/Cursor/Codex/Gemini on the product clone |
| `claude-api` only | No host CLI; still needs product checkout for real code WOs |

If the dashboard shows WOs but host backends never claim, fix `LOCAL_REPO_PATH` first ([Troubleshooting](Troubleshooting)).

If you change `LOCAL_REPO_PATH` after the fact (e.g. via Get Started or Authentication), Docker keeps the old mount until it's recreated. Use the **Remount Docker** action shown on those settings pages (`POST /api/product/remount`, bearer-gated on the draft server and proxied by the orchestrator) to recreate the compose mount without a full image rebuild — see [Getting Started](Getting-Started). A full `make restart` still works as a fallback.

### Runner agent start/stop and pause

`POST /api/runner/agents/{name}/start` and `PUT /api/runner/agents/{name}` (used to configure a host runner agent, including toggling `start: true`) only accept allowlisted agent names — `claude` / `cursor` / `codex` / `gemini` — and allowlisted configure keys (`api_key`, `domain_filter`, `start`). Unknown names or keys return `400`.

Both routes are gated by the factory's pause state: while the factory is paused, starting or configure-starting a runner agent returns `423`, the same way `/api/claim` already refuses while paused. Stop and delete remain allowed while paused so an in-progress drain can finish cleanly.

## Cloud Codex (GitHub Actions)

For WOs with `services: none` (often docs-only), the orchestrator can `workflow_dispatch` the product’s `codex-dispatch.yml` instead of a local runner.

| Requirement | Notes |
|-------------|-------|
| Workflow in **product** | `codex-dispatch.yml` (or `CODEX_WORKFLOW_FILE`) |
| `OPENAI_API_KEY` | Product repo Actions secret — not engine Keychain |
| Poll loop | Detects branch/PR; no callback |

`POST /api/dispatch-codex` pre-claims as `codex-gh-actions`. Second dispatch → 409. Complements host `codex`; does not replace it for service-touching WOs.

## Peer review backends

**Settings → Agents** can force cross-LLM review (default on) so security / architecture / correctness / performance use different models than the implementer. Optional **Review Model** overrides the automation model for review scripts only.

## Antares (security-only)

Cisco Foundation AI's Antares models can be added as a purpose-built vulnerability-localization reviewer alongside the deterministic scanners (Bandit, Semgrep, JS/TS security scan) and the existing LLM peer-review chain. Antares is **disabled by default** and, when enabled, defaults to **advisory** mode — it never blocks a WO on its own findings unless you explicitly switch it to blocking.

Configure it in **Settings → Agents → Reviewer Assignments**:

- **Enable Antares security reviewer** — off by default.
- **Run location** — `This machine` or `Another device on network`.
- **Endpoint URL** — an OpenAI-compatible `POST {ANTARES_BASE_URL}/v1/chat/completions` server.
- **Model profile** — `Auto recommended`, `Antares 350M` (`fdtn-ai/antares-350m`), `Antares 1B` (`fdtn-ai/antares-1b`), or `Custom` (any model name/path, including local GGUF conversions served via llama.cpp or another OpenAI-compatible runtime).
- **Mode** — `Advisory` or `Blocking on configured severities` (CRITICAL/HIGH/MEDIUM/LOW checkboxes).
- **Test Antares Connection** — checks reachability and, if the server exposes `GET /health` or `GET /v1/models`, shows available models; otherwise it shows the configured model with a warning that remote hardware suitability can't be verified.

For local (`This machine`) auto-recommendation, the factory suggests Antares 350M on lower-memory Apple Silicon (M1, ≤8GB) or unknown hardware, and Antares 1B on 16GB+ Macs. It does not guess specs for a remote endpoint.

`Antares` is only selectable for the **Security** reviewer slot — architecture, correctness, performance, and documentation reviewers cannot use it.

When the security reviewer is set to `antares`, `review_chain.py` calls the Antares backend instead of Claude/Codex/Cursor/Gemini, includes prior Bandit/Semgrep/JS findings in its prompt so it can correlate or deduplicate, and posts structured findings (severity, file, line, issue, fix) to the WO thread in the normal review-thread format. `quality_gate.py` can also run an optional Antares scan in parallel with CI/Bandit/Semgrep/JS, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result. In advisory mode, a scan error, timeout, or malformed model response is visible in the thread but never fails `security_passed`; in blocking mode, configured severities (or an unreachable/required Antares) fail `security_passed`.

Source is only sent to a remote endpoint if you explicitly point `ANTARES_BASE_URL` at one — the default is `http://localhost:8000`.

## Relevant WO specs (completed features to document)

### WO-1092-draft-ports-and-remount.md
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

- [x] Cursor / Claude / Codex / Gemini LaunchAgent meta each have distinct `DRAFT_PORT` values matching `health_agent.RUNNER_POR