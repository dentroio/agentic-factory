---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-16
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

Cisco Foundation AI's Antares models can run as an additional **security reviewer** backend, alongside the existing deterministic scanners (Bandit, Semgrep, JS/TS security scan). Antares is purpose-built for vulnerability localization and is meant to complement those scanners, not replace them — Bandit/Semgrep/JS scan stay active whether or not Antares is enabled.

**Disabled by default**, and **advisory by default** when enabled — findings post to the WO thread but never block validation unless you explicitly switch to blocking mode.

Configure in **Settings → Agents → Reviewer Assignments**: Antares is selectable only for the **Security** reviewer slot — architecture, correctness, performance, and documentation reviewers cannot use it.

| Setting | Values |
|---------|--------|
| Run location | This machine, or another device on the LAN |
| Endpoint | OpenAI-compatible `/v1/chat/completions` server, e.g. `ANTARES_BASE_URL=http://localhost:8000` |
| Model profile | Auto recommended, Antares 350M, Antares 1B, Custom |
| Mode | Advisory (default) or Blocking |
| Blocking severities | Any combination of CRITICAL/HIGH/MEDIUM/LOW, used only in blocking mode |

For local mode, the factory recommends a profile from available RAM (e.g. Apple M1 ≤8GB → 350M, ≥16GB → 1B, unknown hardware → 350M). For a remote endpoint it probes `/health` and `/v1/models` if the server exposes them; otherwise it shows the configured model with a warning that remote hardware can't be verified. **Test Antares Connection** checks reachability/model availability without running a full review.

Behavior:

- Antares sees only the WO context, the changed-file diff, and relevant prior scanner findings — never the full repo, and never sent to a cloud endpoint unless you set `ANTARES_BASE_URL` to one yourself.
- Malformed or missing output is a non-blocking scan error in advisory mode.
- In blocking mode, configured severities (default `CRITICAL,HIGH`) fail `security_passed`, and timeout/unreachable/malformed output also fails closed.
- Quality gate results expose `antares_findings`, `antares_error`, and `antares_passed` alongside the existing scanner output.

Env vars (agent-runner): `ANTARES_ENABLED`, `ANTARES_BASE_URL`, `ANTARES_MODEL`, `ANTARES_API_KEY`, `ANTARES_TIMEOUT_SECONDS`, `ANTARES_MODE`, `ANTARES_BLOCKING_SEVERITIES`.