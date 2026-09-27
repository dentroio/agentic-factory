---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-09-27
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

Antares is Cisco Foundation AI's vulnerability-localization model, offered as an optional extra security reviewer alongside the deterministic scanners (Bandit, Semgrep, JS/TS security scan) and the existing LLM peer review chain. It does **not** replace those — it's an additional signal purpose-built for finding and localizing vulnerabilities.

**Disabled by default. Advisory by default.** Blocking mode must be turned on explicitly.

### Configuration (Settings → Agents)

| Field | Options |
|-------|---------|
| Enable Antares security reviewer | on/off |
| Run location | `This machine` or `Another device on network` |
| Endpoint URL | OpenAI-compatible `/v1/chat/completions` server |
| Model profile | Auto recommended, Antares 350M (`fdtn-ai/antares-350m`), Antares 1B (`fdtn-ai/antares-1b`), Custom |
| Mode | Advisory or Blocking on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW checkboxes |
| Test Antares Connection | Probes `/health` and `/v1/models` for reachability and model availability |

For local (`This machine`) runs, **Auto recommended** picks a profile from available memory on Apple Silicon: ≤8GB → Antares 350M, ≥16GB → Antares 1B, unknown hardware → 350M. For a network endpoint, the factory doesn't guess — it probes the remote server's `/health` / `/v1/models` if exposed; otherwise it shows the configured model with a warning that remote hardware can't be verified.

Underlying env vars (set via the client, not manually required):

```text
ANTARES_ENABLED=false
ANTARES_BASE_URL=http://localhost:8000
ANTARES_MODEL=fdtn-ai/antares-350m | fdtn-ai/antares-1b | custom
ANTARES_API_KEY=
ANTARES_TIMEOUT_SECONDS=120
ANTARES_MODE=advisory | blocking
ANTARES_BLOCKING_SEVERITIES=CRITICAL,HIGH
```

### Reviewer assignment

`Antares` is selectable only for the **Security** reviewer role — architecture, correctness, performance, and documentation reviewers cannot be assigned to it. When Security is assigned to Antares, `review_chain.py` calls the Antares endpoint instead of Claude/Cursor/Codex/Gemini and posts structured findings (severity, file, line, issue, fix) to the WO thread in the usual review format, including prior Bandit/Semgrep/JS findings in the prompt so Antares can reason about or deduplicate them.

### Quality gate behavior

An optional Antares scan step runs in `quality_gate.py` alongside CI, Bandit, Semgrep, and the JS security scan — scanning only the changed diff, not the full repo. It contributes `antares_findings`, `antares_error`, and `antares_passed` to the gate result:

- **Advisory mode (default):** findings are visible in the WO thread but never block `security_passed`, even on timeout or malformed output.
- **Blocking mode:** `security_passed` fails when findings at a configured severity are present, or when Antares is required but unreachable (fails closed).

Existing Bandit, Semgrep, JS scan, and Claude/Codex/Cursor/Gemini reviewer behavior is unchanged when Antares is disabled. Source is never sent to a cloud endpoint unless you explicitly point `ANTARES_BASE_URL` at one.