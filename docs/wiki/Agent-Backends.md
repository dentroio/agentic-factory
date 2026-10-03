---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-03
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

Cisco Foundation AI's Antares models can act as the **security reviewer** backend, complementing the deterministic Bandit / Semgrep / JS security scanners rather than replacing them. Antares is purpose-built for vulnerability localization and runs against an OpenAI-compatible endpoint — locally on this Mac or on another device on the LAN.

**Disabled by default; advisory by default.** Enabling Antares never makes it a blocking gate on its own — you must explicitly switch it to blocking mode.

### Configuration (Settings → Agents → Reviewer Assignments)

| Field | Options |
|-------|---------|
| Enable Antares | off by default |
| Run location | `This machine` or `Another device on network` |
| Endpoint URL | `ANTARES_BASE_URL`, default `http://localhost:8000` |
| Model profile | Auto recommended, Antares 350M (`fdtn-ai/antares-350m`), Antares 1B (`fdtn-ai/antares-1b`), Custom |
| Mode | Advisory or Blocking on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW (used only in Blocking mode) |
| Test Antares Connection | checks reachability + available models before any real review runs |

For local runs, **Auto recommended** picks a profile from hardware: Apple M1 with ≤8GB RAM → 350M, ≥16GB RAM → 1B, unknown hardware → 350M. For a network endpoint, the factory probes `GET {ANTARES_BASE_URL}/health` and `GET {ANTARES_BASE_URL}/v1/models` if the remote server exposes them; if it doesn't, the UI shows the configured model with a warning that remote hardware can't be verified.

The **Security** reviewer dropdown is the only reviewer slot that offers `Antares` — architecture, correctness, performance, and documentation reviewers can't select it.

### How it behaves

- Antares receives only the WO context, the changed-file diff, and relevant prior scanner findings — never the full repo — and is asked for security-only, structured JSON findings (severity, file, line, issue, fix).
- Malformed model output is treated as a non-blocking scan error in advisory mode.
- In Blocking mode, Antares findings at a configured severity fail `security_passed`; an unreachable/timed-out Antares also fails closed when Blocking mode is set.
- In `quality_gate.py`, Antares runs in parallel with CI, Bandit, Semgrep, and the JS security scan, contributing `antares_findings` / `antares_error` / `antares_passed` to the result without blocking in advisory mode.
- Existing Bandit, Semgrep, JS scan, and the Claude/Codex/Cursor/Gemini review chain are unchanged when Antares is disabled.

Env vars: `ANTARES_ENABLED`, `ANTARES_BASE_URL`, `ANTARES_MODEL`, `ANTARES_API_KEY`, `ANTARES_TIMEOUT_SECONDS`, `ANTARES_MODE`, `ANTARES_BLOCKING_SEVERITIES`.