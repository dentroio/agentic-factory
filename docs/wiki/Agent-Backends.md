---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-29
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

Antares is an optional, security-only reviewer backend built on Cisco Foundation AI's Antares models, purpose-built for vulnerability localization. It sits alongside — not instead of — the existing deterministic scanners (Bandit for Python, Semgrep, and a JS/TS security scan) and the Claude/Cursor/Codex/Gemini peer review chain.

Antares is **disabled by default**. When enabled, it defaults to **advisory** mode — findings are posted to the WO thread but never block validation on their own. You must explicitly switch it to blocking mode to let it fail the security gate.

### Where it runs

Antares talks to an OpenAI-compatible chat-completions endpoint, which you can run:

- **This machine** — a local server (e.g. llama.cpp or another OpenAI-compatible runtime) on `localhost`
- **Another device on network** — any LAN host serving the same API shape

The factory does not ship or install an Antares model server — you point it at one you run yourself. Source is only sent to the endpoint you configure; nothing is sent to a cloud URL unless you set `ANTARES_BASE_URL` to one.

### Configuration

Settings → Agents → Reviewer Assignments has an Antares section with:

- Enable toggle
- Run location (`This machine` / `Another device on network`) and endpoint URL
- Model profile: `Auto recommended`, `Antares 350M`, `Antares 1B`, or `Custom` (model name/path)
- Mode: `Advisory` or `Blocking on configured severities`
- Blocking severities (CRITICAL / HIGH / MEDIUM / LOW)
- **Test Antares Connection** — checks reachability and, if the endpoint exposes `/health` or `/v1/models`, lists available models

For local runs, the UI recommends a profile from available memory (Apple M1 ≤ 8GB → 350M, ≥ 16GB → 1B, unknown hardware → 350M). For a remote endpoint it probes `/health` and `/v1/models` if available; otherwise it shows the configured model with a note that remote hardware can't be verified.

| Env var | Default | Purpose |
|---------|---------|---------|
| `ANTARES_ENABLED` | `false` | Turn the backend on |
| `ANTARES_BASE_URL` | `http://localhost:8000` | OpenAI-compatible endpoint |
| `ANTARES_MODEL` | — | `fdtn-ai/antares-350m`, `fdtn-ai/antares-1b`, or a custom value |
| `ANTARES_API_KEY` | — | Optional, for secured endpoints |
| `ANTARES_TIMEOUT_SECONDS` | `120` | Request timeout |
| `ANTARES_MODE` | `advisory` | `advisory` or `blocking` |
| `ANTARES_BLOCKING_SEVERITIES` | `CRITICAL,HIGH` | Severities that fail the gate in blocking mode |

### Reviewer assignment and gate behavior

Antares can only be assigned to the **Security** reviewer slot — it is not offered for architecture, correctness, performance, or documentation review. When assigned, `review_chain.py` routes the security review to Antares instead of Claude/Cursor/Codex/Gemini, sends it the WO context, changed-file diff, and prior Bandit/Semgrep/JS findings, and requires structured JSON findings (severity, file, line, issue, fix) before posting to the WO thread.

`quality_gate.py` can also run an optional Antares scan over changed files in parallel with CI, Bandit, Semgrep, and the JS scan, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result:

- **Advisory mode** — findings are visible but never fail `security_passed`; malformed output or a timeout is logged as a non-blocking scan error.
- **Blocking mode** — configured severities fail `security_passed`, and an unreachable/unavailable endpoint fails closed since Antares was explicitly required.

Existing Bandit, Semgrep, JS-scan, and non-security peer review behavior is unchanged whether or not Antares is en