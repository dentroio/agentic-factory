---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-23
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

Antares is an optional security-focused reviewer backend from Cisco Foundation AI, purpose-built for vulnerability localization. It complements the existing deterministic scanners (Bandit for Python, Semgrep, and a JS/TS security scan) rather than replacing them — those scanners stay active whether or not Antares is enabled.

Antares is **disabled by default**, and when enabled defaults to **advisory** mode (findings never block validation). Blocking mode must be explicitly configured.

### Run location and model profiles

Antares can run:
- **This machine** — local OpenAI-compatible server (e.g. `llama.cpp` serving a GGUF)
- **Another device on network** — any LAN host exposing an OpenAI-compatible endpoint

Model profile options:

| Profile | Model value | Intended use |
|---------|-------------|--------------|
| Auto recommended | `auto` | Factory recommends a profile from local hardware (or the remote server's `/v1/models` response) |
| Antares 350M | `fdtn-ai/antares-350m` | Lower-memory Macs, M1 8GB, CPU-only/shared machines |
| Antares 1B | `fdtn-ai/antares-1b` | M1/M2/M3 16GB+, higher-quality local review |
| Custom | user supplied | GGUF paths, future Antares releases, remote GPU hosts |

For local mode the factory recommends 350M on ≤8GB Apple Silicon, 1B on ≥16GB, and 350M when hardware is unknown. For network mode it probes `{ANTARES_BASE_URL}/health` and `{ANTARES_BASE_URL}/v1/models` when available; if the remote server doesn't expose model metadata, the UI shows the configured model with a warning that remote hardware suitability can't be verified.

### Configuration

Configure under **Settings → Agents / Reviewer Assignments**: enable toggle, run location, endpoint URL, model profile (+ custom value), mode (advisory/blocking), blocking severities (CRITICAL/HIGH/MEDIUM/LOW), and a **Test Antares Connection** button that checks reachability and model availability without running a full review.

Underlying env vars:

```text
ANTARES_ENABLED=false
ANTARES_BASE_URL=http://localhost:8000
ANTARES_MODEL=fdtn-ai/antares-350m | fdtn-ai/antares-1b | custom
ANTARES_API_KEY=
ANTARES_TIMEOUT_SECONDS=120
ANTARES_MODE=advisory | blocking
ANTARES_BLOCKING_SEVERITIES=CRITICAL,HIGH
```

Antares only runs against the changed-file diff (plus prior scanner findings for context) — never the full repo — and it's never sent to a remote endpoint unless you explicitly point `ANTARES_BASE_URL` at one.

### Reviewer assignment and gating

`Antares` is selectable only for the **Security** reviewer slot — architecture, correctness, performance, and documentation reviewers do not offer it. When assigned, `review_chain.py` routes the security review through Antares instead of Claude/Codex/Cursor/Gemini and posts structured findings (severity, file, line, issue, fix) to the WO thread in the existing review-thread format.

`quality_gate.py` can also run an optional Antares scan in parallel with CI, Bandit, Semgrep, and the JS security scan, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result:

- **Advisory mode** — findings are visible in the WO thread but never fail `security_passed`. Malformed output or an unreachable endpoint is treated as a non-blocking scan error.
- **Blocking mode** — `security_passed` fails when configured severities (e.g. CRITICAL/HIGH) are found, and fails closed if Antares is required but unreachable.

Existing Bandit/Semgrep/JS scanning and the Claude/Codex/Cursor/Gemini reviewer behavior are unchanged when Antares is disabled.