---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-08
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

[Cisco Foundation AI's Antares](https://huggingface.co/fdtn-ai) is an optional, purpose-built vulnerability-localization model that can serve as the **Security** peer reviewer, complementing (not replacing) the existing Bandit / Semgrep / JS security scanners. It's **disabled by default**, and when enabled it runs in **advisory** mode unless you explicitly set it to blocking.

### Where Antares runs

Antares is an OpenAI-compatible chat-completions endpoint — run it on this Mac or on another device on your LAN:

| Setting | Values |
|---------|--------|
| `ANTARES_ENABLED` | `false` (default) / `true` |
| `ANTARES_BASE_URL` | e.g. `http://localhost:8000` or a LAN host |
| `ANTARES_MODEL` | `auto` / `fdtn-ai/antares-350m` / `fdtn-ai/antares-1b` / custom value or path |
| `ANTARES_API_KEY` | optional, for secured endpoints |
| `ANTARES_TIMEOUT_SECONDS` | default `120` |
| `ANTARES_MODE` | `advisory` (default) / `blocking` |
| `ANTARES_BLOCKING_SEVERITIES` | e.g. `CRITICAL,HIGH` (only matters in blocking mode) |

The factory never sends source code to a cloud endpoint unless you configure `ANTARES_BASE_URL` to point at one.

### Model profiles

| Profile | Model value | Intended use |
|---------|-------------|---------------|
| Auto recommended | `auto` | Factory recommends a profile from local hardware (or the remote `/models` response) |
| Antares 350M | `fdtn-ai/antares-350m` | Lower-memory Macs — M1 with ≤8GB RAM, CPU-only/shared machines |
| Antares 1B | `fdtn-ai/antares-1b` | M1/M2/M3 with ≥16GB RAM — higher-quality local review |
| Custom | user-supplied | GGUF paths, future Antares releases, remote GPU hosts |

For a network endpoint, the factory probes `GET {ANTARES_BASE_URL}/health` and `/v1/models` for metadata; if the remote server doesn't expose that, it shows the configured model with a warning that remote hardware suitability can't be verified.

### Configuring it

In **Settings → Agents**, the Antares section has: enable toggle, run location (this machine / another device), endpoint URL, model profile picker, custom model field, advisory/blocking mode, blocking-severity checkboxes (CRITICAL/HIGH/MEDIUM/LOW), and a **Test Antares Connection** button that checks reachability and available models without running a full review.

Once enabled, `Antares` becomes a selectable backend for the **Security** reviewer slot only — it is not offered for architecture, correctness, performance, or documentation reviewers.

### Behavior in review and gates

- `review_chain.py` routes the security reviewer to Antares when assigned, posting structured findings (severity, file, line, issue, fix) to the WO thread in the normal review-thread format, with prior Bandit/Semgrep/JS findings included in the prompt for context.
- `quality_gate.py` can run an optional Antares scan in parallel with CI/Bandit/Semgrep/JS, scanning only the changed diff. It reports `antares_findings`, `antares_error`, and `antares_passed`, and adds findings to the overall `finding_count`.
- **Advisory mode** (default): Antares findings and errors are visible but never block validation.
- **Blocking mode**: `security_passed` fails if configured severities are found, or if Antares is required but unreachable (fails closed).
- Existing Bandit, Semgrep, JS scan, and Claude/Codex/Cursor/Gemini reviewer behavior is unchanged when Antares is disabled.