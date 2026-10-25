---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-25
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

Antares (Cisco Foundation AI) is an optional reviewer backend purpose-built for vulnerability localization. It's a complement to the deterministic scanners (Bandit, Semgrep, JS security scan) — not a replacement — and can only be assigned to the **Security** reviewer slot. Architecture, correctness, performance, and documentation reviewers cannot select Antares.

**Disabled by default.** When enabled, it defaults to **advisory** mode — findings post to the WO thread but never fail the gate — until an operator explicitly switches it to blocking.

### Configuration

Configure in **Settings → Agents / Reviewer Assignments**:

| Setting | Options |
|---------|---------|
| Enable Antares security reviewer | on/off |
| Run location | This machine / Another device on network |
| Endpoint URL | OpenAI-compatible `/v1/chat/completions` endpoint |
| Model profile | Auto recommended, Antares 350M, Antares 1B, Custom |
| Mode | Advisory or Blocking on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW |

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

For local (`This machine`) runs, the factory recommends a model profile from available hardware (e.g. Apple M1 ≤8GB → 350M, ≥16GB → 1B). For a network endpoint it won't guess remote specs — it probes `GET {ANTARES_BASE_URL}/health` and `/v1/models` if the remote service exposes them, otherwise it shows the configured model with a warning that remote suitability can't be verified. Use **Test Antares Connection** in Settings to check reachability and model availability without running a full review.

### Behavior

- Only the WO context, changed-file diff, and relevant prior scanner findings are sent to Antares — never the full repo, and never to a cloud endpoint unless you explicitly point `ANTARES_BASE_URL` at one.
- Antares output must be structured JSON (severity, file, line, issue, fix); malformed output is treated as a non-blocking scan error in advisory mode.
- In **advisory** mode, Antares findings (or a failed/unreachable endpoint) never fail `security_passed` — they're still visible in the WO thread.
- In **blocking** mode, `security_passed` fails when configured severities (e.g. CRITICAL/HIGH) are found, and fails closed if Antares is required but unreachable.
- Existing Bandit, Semgrep, JS security scan, and the Claude/Codex/Cursor/Gemini reviewer chain are unchanged when Antares is disabled.