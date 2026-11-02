---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-11-02
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

For WOs with `services: none` (often docs-only), the orchestrator can `workflow_dispatch` the product's `codex-dispatch.yml` instead of a local runner.

| Requirement | Notes |
|-------------|-------|
| Workflow in **product** | `codex-dispatch.yml` (or `CODEX_WORKFLOW_FILE`) |
| `OPENAI_API_KEY` | Product repo Actions secret — not engine Keychain |
| Poll loop | Detects branch/PR; no callback |

`POST /api/dispatch-codex` pre-claims as `codex-gh-actions`. Second dispatch → 409. Complements host `codex`; does not replace it for service-touching WOs.

## Peer review backends

**Settings → Agents** can force cross-LLM review (default on) so security / architecture / correctness / performance use different models than the implementer. Optional **Review Model** overrides the automation model for review scripts only.

## Antares (security-only)

[Cisco Foundation AI's Antares](https://huggingface.co/fdtn-ai) is an optional local or LAN-hosted security reviewer, purpose-built for vulnerability localization. It complements — not replaces — the deterministic Bandit, Semgrep, and JS/TS security scanners, and the existing peer review chain. It is **disabled by default**, and when enabled it defaults to **advisory** mode.

Antares can only be assigned to the **Security** reviewer slot — it is not selectable for architecture, correctness, performance, or documentation review.

### Configuration

Set up under **Settings → Agents → Reviewer Assignments**:

| Field | Options |
|-------|---------|
| Enable Antares | off (default) / on |
| Run location | This machine / Another device on network |
| Endpoint URL | `ANTARES_BASE_URL` (default `http://localhost:8000`, OpenAI-compatible `/v1/chat/completions`) |
| Model profile | Auto recommended, Antares 350M, Antares 1B, Custom |
| Mode | Advisory (default) / Blocking on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW (when Blocking) |

Corresponding env vars: `ANTARES_ENABLED`, `ANTARES_BASE_URL`, `ANTARES_MODEL`, `ANTARES_API_KEY`, `ANTARES_TIMEOUT_SECONDS`, `ANTARES_MODE`, `ANTARES_BLOCKING_SEVERITIES`.

For local runs, the factory recommends a model profile from available Mac hardware (M1 ≤8GB → 350M, M1/M2/M3 ≥16GB → 1B, unknown → 350M). For a network endpoint it probes `GET {ANTARES_BASE_URL}/health` and `/v1/models` when available; if the remote server doesn't expose model metadata, the UI shows the configured model with a warning that remote hardware can't be verified.

**Test Antares Connection** in Settings checks reachability and model availability without running a full review.

### How it behaves

- Security review findings from Antares post to the WO thread in the standard review-thread format, alongside prior Bandit/Semgrep/JS findings (included in the Antares prompt so it can deduplicate or localize related issues).
- **Advisory mode** (default): findings are visible but never block validation, even on timeout, unreachable endpoint, or malformed output.
- **Blocking mode**: `security_passed` fails when configured severities (e.g. CRITICAL/HIGH) are found, and fails closed if Antares is required but unreachable.
- Source is never sent to a non-local endpoint unless you explicitly point `ANTARES_BASE_URL` at one.
- Only the WO context, changed-file diff, and relevant prior scanner findings are sent — not the full repository.

`services/agent-runner/quality_gate.py` runs an optional Antares scan in parallel with CI, Bandit, Semgrep, and the JS security scan, contributing `antares_findings` / `antares_error` / `antares_passed` to the structured gate result.