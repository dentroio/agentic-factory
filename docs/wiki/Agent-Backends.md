---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-09-30
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

Optional [Cisco Foundation AI Antares](https://huggingface.co/fdtn-ai) reviewer that complements the existing deterministic scanners (Bandit for Python, Semgrep for rule-based static analysis, and a JS/TS security scan) — Antares is purpose-built for vulnerability localization, not a replacement for those scanners.

**Disabled by default.** When enabled, it's **advisory by default** (findings are posted to the WO review thread but never block validation); it can be switched to **blocking** on configured severities through explicit configuration.

Run it locally on this Mac or on another device on your LAN — Antares never leaves the machine you point it at unless you explicitly configure a remote/cloud `ANTARES_BASE_URL`. Configuration (agent-runner env, mirrored in Settings → Agents):

| Variable | Values |
|----------|--------|
| `ANTARES_ENABLED` | `false` (default) / `true` |
| `ANTARES_BASE_URL` | OpenAI-compatible endpoint, e.g. `http://localhost:8000` |
| `ANTARES_MODEL` | `auto` / `fdtn-ai/antares-350m` / `fdtn-ai/antares-1b` / custom |
| `ANTARES_API_KEY` | optional, for authenticated endpoints |
| `ANTARES_TIMEOUT_SECONDS` | default `120` |
| `ANTARES_MODE` | `advisory` (default) / `blocking` |
| `ANTARES_BLOCKING_SEVERITIES` | e.g. `CRITICAL,HIGH` |

**Settings → Agents** exposes: enable toggle, run location (**This machine** / **Another device on network**), endpoint URL, model profile picker, custom model field, mode (advisory/blocking), blocking-severity checkboxes, and a **Test Antares Connection** button that reports reachability and available models without running a full review.

For local (Apple Silicon) hosting, the UI recommends a model profile from available memory:

| Hardware | Recommended profile |
|----------|---------------------|
| Apple M1 + ≤8GB RAM | Antares 350M |
| Apple M1/M2/M3 + ≥16GB RAM | Antares 1B |
| Unknown / can't detect | Antares 350M |

For a remote/LAN endpoint, the factory probes `GET /health` and `GET /v1/models` if the remote server exposes them; if it doesn't, the UI shows the configured model with a warning that remote hardware suitability can't be verified.

Antares is selectable **only** for the Security reviewer role in reviewer assignments — architecture, correctness, performance, and documentation reviewers do not offer it. When assigned, `review_chain.py` routes the security review to Antares instead of Claude/Codex/Cursor/Gemini, including prior Bandit/Semgrep/JS findings in its prompt so it can deduplicate or localize related issues. `quality_gate.py` can also run Antares in parallel with CI/Bandit/Semgrep/JS as an optional scan step, adding `antares_findings` / `antares_error` / `antares_passed` to the gate result.

Malformed model output, timeouts, or connection failures are treated as a non-blocking scan error in advisory mode; they only fail `security_passed` when Antares is explicitly configured as blocking (or required and unreachable).