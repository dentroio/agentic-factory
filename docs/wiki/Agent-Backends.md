---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-20
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

Optional **Cisco Foundation AI Antares** reviewer, purpose-built for vulnerability localization. It complements — rather than replaces — the deterministic Bandit, Semgrep, and JS/TS security scanners and the existing cross-LLM review chain.

Antares is **disabled by default**, and when enabled defaults to **advisory** mode. Configure it in **Settings → Agents**:

| Setting | Options | Notes |
|---------|---------|-------|
| Enable Antares security reviewer | off / on | `ANTARES_ENABLED` |
| Run location | This machine / Another device on network | sets `ANTARES_BASE_URL` (defaults to `http://localhost:8000`) |
| Model profile | Auto recommended, Antares 350M, Antares 1B, Custom | Auto recommends `fdtn-ai/antares-350m` for Apple M1 with ≤8GB RAM or unknown hardware, `fdtn-ai/antares-1b` for M1/M2/M3 with ≥16GB RAM. For a network endpoint, the factory probes `GET /health` and `GET /v1/models` on the remote service and shows a warning if it can't verify remote hardware |
| Custom model | string | For GGUF paths or other model names served via an OpenAI-compatible runtime |
| Mode | Advisory / Blocking on configured severities | Advisory never blocks validation; Blocking fails `security_passed` for the configured severities and fails closed if Antares is required but unreachable |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW | Only used in Blocking mode |
| Test Antares Connection | button | Checks endpoint reachability and lists available models without running a full review |

Antares can only be selected for the **Security** reviewer slot — it is not offered for architecture, correctness, performance, or documentation reviewers.

When assigned, `review_chain.py` routes the security reviewer through an OpenAI-compatible call (`POST {ANTARES_BASE_URL}/v1/chat/completions`), sending the WO context, changed-file diff, and prior Bandit/Semgrep/JS findings, and posts structured findings (severity, file, line, issue, fix) to the WO thread in the existing review format. `quality_gate.py` can optionally run an Antares scan in parallel with CI/Bandit/Semgrep/JS, contributing `antares_findings`, `antares_error`, and `antares_passed` to the gate result and to the overall `finding_count`. Malformed model output or a timeout is treated as a non-blocking scan error in advisory mode; in blocking mode, timeout/connection failure/malformed output block the gate.

Env vars (set by the Settings UI, or directly if self-hosting): `ANTARES_ENABLED`, `ANTARES_BASE_URL`, `ANT