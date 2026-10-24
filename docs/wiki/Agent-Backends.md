---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-24
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

[Cisco Foundation AI](https://developer.cisco.com) Antares is an optional, purpose-built vulnerability-localization model that plugs into the **security** reviewer slot alongside the existing deterministic scanners (Bandit, Semgrep, JS security scan). It complements those scanners rather than replacing them, and it is **disabled by default**; when enabled it defaults to **advisory** mode.

### Where it runs

Antares talks to an OpenAI-compatible chat-completions endpoint, hosted either:

- **This machine** — a local server (e.g. llama.cpp serving a GGUF build), or
- **Another device on the network** — any LAN host exposing the same API

Source/diff content is only sent to the endpoint you configure — never to a cloud service unless you explicitly point `ANTARES_BASE_URL` at one.

### Configuration

| Setting | Values | Notes |
|---------|--------|-------|
| `ANTARES_ENABLED` | `false` (default) / `true` | Master switch |
| `ANTARES_BASE_URL` | e.g. `http://localhost:8000` | OpenAI-compatible endpoint |
| `ANTARES_MODEL` | `auto`, `fdtn-ai/antares-350m`, `fdtn-ai/antares-1b`, custom | Model profile |
| `ANTARES_API_KEY` | — | Optional, for secured endpoints |
| `ANTARES_TIMEOUT_SECONDS` | default `120` | Request timeout |
| `ANTARES_MODE` | `advisory` (default) / `blocking` | Advisory never fails the gate |
| `ANTARES_BLOCKING_SEVERITIES` | e.g. `CRITICAL,HIGH` | Only applies in blocking mode |

**Model profiles:** `auto` recommends a profile from local hardware (Apple Silicon ≤8GB RAM → 350M, ≥16GB → 1B, unknown → 350M) or from the remote server's `/health` / `/v1/models` response when run on the network. If a remote endpoint doesn't expose model metadata, the UI shows the configured model with a warning that remote hardware can't be verified.

Configure all of this in **Settings → Agents** under the Antares section: enable toggle, run location, endpoint URL, model profile (with a **Custom** option for GGUF paths or other model names), advisory/blocking mode, blocking-severity checkboxes, and a **Test Antares Connection** button that checks reachability and available models without running a full review.

Only the **Security** reviewer can be set to `antares` — architecture, correctness, performance, and documentation reviewer slots don't offer it.

### Behavior

- **Review chain** — when the security reviewer is set to `antares`, it's called instead of Claude/Codex/Cursor/Gemini for that role. Findings are posted to the WO thread in the same structured format, and prior Bandit/Semgrep/JS findings are included in the prompt so Antares can deduplicate or localize related issues.
- **Quality gate** — an optional Antares scan runs in parallel with CI/Bandit/Semgrep/JS on changed files only, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result.
- **Advisory mode** (default) — Antares findings and errors are visible but never fail `security_passed`.
- **Blocking mode** — `security_passed` fails when configured severities are found, or when Antares is required but unreachable/times out/returns malformed output.
- Existing Bandit, Semgrep, JS scan, and the Claude/Codex/Cursor/Gemini review chain are unaffected when Antares is disabled.