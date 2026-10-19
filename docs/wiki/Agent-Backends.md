---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-19
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

Optional [Cisco Foundation AI](https://developer.cisco.com/) Antares reviewer for the **Security** role only — it is not selectable for architecture, correctness, performance, or documentation reviewers. Disabled by default; when enabled it defaults to **advisory** mode.

Configure in **Settings → Agents**:

- Enable Antares security reviewer
- Run location: **This machine** or **Another device on network**
- Endpoint URL (`ANTARES_BASE_URL`, default `http://localhost:8000`, an OpenAI-compatible `/v1/chat/completions` server)
- Model profile: **Auto recommended**, **Antares 350M** (`fdtn-ai/antares-350m`), **Antares 1B** (`fdtn-ai/antares-1b`), or **Custom** (any model name/path, e.g. a llama.cpp GGUF path)
- Mode: **Advisory** (default) or **Blocking** on configured severities (CRITICAL / HIGH / MEDIUM / LOW)
- **Test Antares Connection** — checks reachability and, if the endpoint exposes `/health` or `/v1/models`, lists available models and the current recommendation

For local Apple Silicon, Auto recommends Antares 350M on ≤8GB RAM and Antares 1B on ≥16GB RAM (350M on unknown hardware). For a network endpoint the factory can't infer remote hardware — it shows the configured model plus a warning if the remote server doesn't expose model metadata.

Antares runs alongside Bandit, Semgrep, and the JS/TS security scanner in `quality_gate.py` (diff-only, not a full-repo scan) and, when assigned as the Security reviewer, posts structured findings (severity, file, line, issue, fix) to the WO thread via `review_chain.py`, including prior scanner findings for context. In **advisory** mode, a timeout, unreachable endpoint, or malformed response never blocks validation — findings or errors are still visible in the thread. In **blocking** mode, configured severities fail `security_passed`, and an unreachable/required Antares fails closed. Existing Bandit/Semgrep/JS scans and the Claude/Codex/Cursor/Gemini reviewer chain are unaffected when Antares is disabled.

| Env var | Default | Notes |
|---|---|---|
| `ANTARES_ENABLED` | `false` | Master switch |
| `ANTARES_BASE_URL` | `http://localhost:8000` | OpenAI-compatible endpoint; local or LAN |
| `ANTARES_MODEL` | — | `fdtn-ai/antares-350m`, `fdtn-ai/antares-1b`,