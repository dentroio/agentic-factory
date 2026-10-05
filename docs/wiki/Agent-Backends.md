---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-05
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

Optional security reviewer backend from Cisco Foundation AI, purpose-built for vulnerability localization. It runs **alongside**, not instead of, the existing Bandit, Semgrep, and JS/TS security scanners, and alongside the Claude/Cursor/Codex/Gemini peer-review chain.

- **Disabled by default.** Enable it in **Settings → Agents** under the security reviewer / Antares section.
- **Run location:** `This machine` or `Another device on network` — Antares talks to any OpenAI-compatible endpoint (`POST {ANTARES_BASE_URL}/v1/chat/completions`).
- **Model profile:**
  - `auto` (recommended) — the factory suggests a profile for local Apple Silicon (≤8GB RAM → Antares 350M, ≥16GB RAM → Antares 1B; unknown hardware defaults to 350M). For a remote endpoint it probes `GET /health` / `GET /v1/models` if available, and otherwise shows the configured model with a warning that remote hardware can't be verified.
  - `fdtn-ai/antares-350m` — lower-memory / CPU-only machines
  - `fdtn-ai/antares-1b` — higher-quality local review on 16GB+ Apple Silicon
  - Custom — any model name or local GGUF path served through an OpenAI-compatible runtime
- **Mode:**
  - `advisory` (default) — findings are posted to the WO review thread but never block validation, even on malformed output or a timeout.
  - `blocking` — `security_passed` fails when findings match the configured blocking severities (default `CRITICAL,HIGH`), or when Antares is required but unreachable.
- **Test Antares Connection** checks endpoint reachability and, when the server exposes model metadata, confirms the selected model is available — without running a full review.
- Antares is selectable **only** for the **Security** reviewer slot in manual reviewer assignment; it is not offered for architecture, correctness, performance, or documentation reviewers.

Relevant env vars (agent-runner):

| Variable | Default | Purpose |
|---|---|---|
| `ANTARES_ENABLED` | `false` | Master on/off toggle |
| `ANTARES_BASE_URL` | `http://localhost:8000` | OpenAI-compatible endpoint (local or LAN) |
| `ANTARES_MODEL` | — | `fdtn-ai/antares-350m`, `f