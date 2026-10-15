---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-15
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

Antares is Cisco Foundation AI's vulnerability-localization model, available as an optional backend for the **Security** reviewer role only — it is never selectable for architecture, correctness, performance, or documentation review. It complements the existing deterministic scanners (Bandit, Semgrep, JS/TS security scan) rather than replacing them.

**Disabled by default.** When enabled, it defaults to **advisory** mode and must be switched to blocking explicitly.

### Run location

- **This machine** — local OpenAI-compatible endpoint (e.g. `llama.cpp` server)
- **Another device on network** — any reachable OpenAI-compatible endpoint (LAN or remote); source is never sent off-box unless you point the endpoint at one explicitly

### Configuration (Settings → Agents → Antares)

| Setting | Values | Notes |
|---------|--------|-------|
| Enable Antares security reviewer | on/off | Off by default |
| Run location | This machine / Another device on network | |
| Endpoint URL | `ANTARES_BASE_URL` | e.g. `http://localhost:8000` |
| Model profile | Auto recommended / Antares 350M / Antares 1B / Custom | |
| Custom model value | string/path | GGUF paths, remote model IDs |
| Mode | Advisory / Blocking | Blocking requires explicit opt-in |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW | Only used in blocking mode |
| Test Antares Connection | button | Checks reachability + model availability without running a full review |

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

### Model profile recommendation

For **local** mode, the factory recommends a profile from Mac hardware:

```text
Apple M1 + <= 8GB RAM  -> Antares 350M
Apple M1 + >= 16GB RAM -> Antares 1B
Unknown hardware       -> Antares 350M
```

For **network** mode, the factory probes `GET {ANTARES_BASE_URL}/health` and `GET {ANTARES_BASE_URL}/v1/models` if the remote server exposes them; if it doesn't, the UI shows the configured model with a warning that remote hardware suitability can't be verified.

### Review and gate behavior

- Security reviewer assigned to `antares` routes that role's review through the Antares endpoint instead of Claude/Cursor/Codex/Gemini; findings are posted to the WO thread in the existing review format, with prior Bandit/Semgrep/JS findings included in the prompt for context/deduplication.
- `quality_gate.py` can optionally run an Antares scan over changed files/diff in parallel with CI, Bandit, Semgrep, and the JS security scan, contributing `antares_findings` / `antares_error` / `antares_passed` to the gate result.
- **Advisory mode** (default): findings are visible but never block `security_passed`, even on scan error or malformed model output.
- **Blocking mode**: `security_passed` fails when configured severities are present, or when Antares is required but unreachable/times out.
- Existing Bandit, Semgrep, JS scan, and the Claude/Cursor/Codex/Gemini review chain are unaffected when Antares is disabled.

## Relevant design docs
None provided.