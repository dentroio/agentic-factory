---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-17
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

[Cisco Foundation AI's Antares](https://huggingface.co/fdtn-ai) is an optional, security-only reviewer backend, purpose-built for vulnerability localization. It complements — not replaces — the deterministic scanners (Bandit, Semgrep, JS security scan) and the existing peer review chain. It is **disabled by default** and runs in **advisory mode** by default; blocking must be turned on explicitly.

Configure it in **Settings → Agents → Reviewer Assignments**:

- **Enable Antares security reviewer** toggle
- **Run location** — `This machine` or `Another device on network`
- **Endpoint URL** — an OpenAI-compatible `/v1/chat/completions` server
- **Model profile** — Auto recommended, Antares 350M, Antares 1B, or Custom (model ID/path)
- **Mode** — Advisory (findings posted, never blocks) or Blocking on configured severities
- **Blocking severities** — CRITICAL / HIGH / MEDIUM / LOW checkboxes
- **Test Antares Connection** — checks reachability and, if the server exposes `/health` or `/v1/models`, lists available models

For local Apple Silicon, the factory recommends a profile from available memory (M1 ≤8GB → 350M, M1/M2/M3 ≥16GB → 1B; unknown hardware defaults to 350M). For a network endpoint it probes `/health` / `/v1/models` instead of guessing; if the remote server doesn't expose model metadata, the UI shows the configured model with a warning that remote hardware can't be verified.

Equivalent env vars (agent-runner):

```text
ANTARES_ENABLED=false
ANTARES_BASE_URL=http://localhost:8000
ANTARES_MODEL=fdtn-ai/antares-350m | fdtn-ai/antares-1b | custom
ANTARES_API_KEY=
ANTARES_TIMEOUT_SECONDS=120
ANTARES_MODE=advisory | blocking
ANTARES_BLOCKING_SEVERITIES=CRITICAL,HIGH
```

Only the **Security** reviewer slot can be set to `antares` — architecture, correctness, performance, and documentation reviewers don't offer it. When assigned, `review_chain.py` routes the security review to Antares instead of Claude/Cursor/Codex/Gemini, includes prior Bandit/Semgrep/JS findings in its prompt, and posts structured findings (severity, file, line, issue, fix) to the WO thread in the normal review format. `quality_gate.py` can also run Antares in parallel with CI/Bandit/Semgrep/JS scan, scanning only the changed diff; its results surface as `antares_findings` / `antares_error` / `antares_passed`.

In advisory mode, Antares findings or failures are visible in the WO thread but never fail the gate. In blocking mode, `security_passed` fails if configured severities are found, or if Antares is required but unreachable/malformed (fail closed). Model output is treated as untrusted and validated before use.