---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-18
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

[Cisco Foundation AI](https://huggingface.co/fdtn-ai) Antares models are an optional, purpose-built **security reviewer** backend — complementary to the deterministic Bandit (Python), Semgrep, and JS/TS scanners already in the quality gate, not a replacement for them. Antares can run locally on the factory Mac or on another device on the LAN.

Antares is **disabled by default**, and when enabled defaults to **advisory** mode — it never blocks validation on its own unless you explicitly switch it to blocking.

### Settings → Agents

- **Enable Antares security reviewer** — on/off.
- **Run location** — `This machine` or `Another device on network` (endpoint URL).
- **Model profile** — Auto recommended, Antares 350M (`fdtn-ai/antares-350m`), Antares 1B (`fdtn-ai/antares-1b`), or Custom (model name/path — supports local GGUF conversions served through an OpenAI-compatible runtime).
- **Mode** — Advisory or Blocking on configured severities (CRITICAL/HIGH/MEDIUM/LOW checkboxes).
- **Test Antares Connection** — checks reachability and, if the endpoint exposes `GET /health` or `GET /v1/models`, shows available models; otherwise shows a warning that remote hardware/model fit can't be verified.

For local `Auto recommended`, the factory suggests Antares 350M on Apple M1 with ≤8GB RAM, Antares 1B on 16GB+ Apple Silicon, and 350M when hardware is unknown.

Only the **Security** reviewer slot can be set to `antares` — architecture, correctness, performance, and documentation reviewers don't offer it.

### How it's used

- `review_chain.py` routes the security reviewer to Antares (instead of Claude/Codex/Cursor/Gemini) when assigned, sending the WO context, changed-file diff, and prior Bandit/Semgrep/JS findings, and posts structured findings (severity, file, line, issue, fix) to the WO thread in the normal review format.
- `quality_gate.py` can optionally run an Antares scan on changed files in parallel with CI/Bandit/Semgrep/JS, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result.
- **Advisory mode** (default when enabled): findings are posted and visible, but never flip `security_passed` to false, and a malformed/unreachable response is treated as a non-blocking scan error.
- **Blocking mode**: `security_passed` fails when configured severities (e.g. CRITICAL/HIGH) are found, and fails closed if Antares is required but unreachable or times out.

Relevant env vars (set via Settings, not hand-edited): `ANTARES_ENABLED`, `ANTARES_BASE_URL`, `ANTARES_MODEL`, `ANTARES_API_KEY`, `ANTARES_TIMEOUT_SECONDS`, `ANTARES_MODE`, `ANTARES_BLOCKING_SEVERITIES`.