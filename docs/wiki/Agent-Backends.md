---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-09-29
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

Cisco Foundation AI's **Antares** models are a purpose-built vulnerability-localization reviewer that complements the deterministic scanners (Bandit, Semgrep, JS security scan) rather than replacing them. Antares is disabled by default and, when enabled, is **advisory by default** — it can only block validation once you explicitly switch it to blocking mode.

Configure it in **Settings → Agents → Reviewer Assignments**:

| Field | Options |
|-------|---------|
| Enable Antares security reviewer | off by default |
| Run location | `This machine` or `Another device on network` |
| Endpoint URL | e.g. `http://localhost:8000` |
| Model profile | Auto recommended, Antares 350M, Antares 1B, Custom |
| Mode | Advisory or Blocking on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW (only used in Blocking mode) |
| Test Antares Connection | checks reachability and lists available models when the endpoint exposes them |

**Model profiles** — for local runs, the factory recommends `fdtn-ai/antares-350m` on lower-memory Apple Silicon (M1 with ≤8GB RAM or unknown hardware) and `fdtn-ai/antares-1b` on M1/M2/M3 with ≥16GB RAM. For a network endpoint, the factory probes `/health` and `/v1/models` if the remote server exposes them; otherwise it shows the configured model with a warning that remote hardware can't be verified. `Custom` accepts any model name or path (e.g. a GGUF served through llama.cpp).

**Reviewer assignment** — Antares can only be assigned to the **Security** reviewer role; it does not appear as an option for architecture, correctness, performance, or documentation review.

**Behavior in the review chain and quality gate:**
- When Security is assigned to Antares, `review_chain.py` calls the Antares endpoint (`POST {ANTARES_BASE_URL}/v1/chat/completions`, OpenAI-compatible) with the WO context, changed-file diff, and prior Bandit/Semgrep/JS findings, and posts structured findings to the WO thread.
- `quality_gate.py` can optionally run an Antares scan of changed files alongside CI/Bandit/Semgrep/JS, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result.
- **Advisory mode** (default): Antares findings and errors are visible in the WO thread but never block `security_passed`.
- **Blocking mode**: `security_passed` fails when Antares reports a configured severity (CRITICAL/HIGH by default), and fails closed if Antares is required but unreachable or times out.
- Existing Bandit, Semgrep, JS scan, and Claude/Codex/Cursor/Gemini reviewer behavior is unchanged when Antares is disabled.

Source code is never sent to a remote endpoint unless you explicitly point `ANTARES_BASE_URL` at one — the default is `localhost`.