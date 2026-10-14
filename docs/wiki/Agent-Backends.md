---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-10-14
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

[Cisco Foundation AI's Antares](https://huggingface.co/fdtn-ai) is an optional security reviewer backend, purpose-built for vulnerability localization. It complements the deterministic scanners (Bandit, Semgrep, JS/TS security scan) rather than replacing them — it is **disabled by default**, and when enabled it is **advisory by default**.

Configure it in **Settings → Agents** (Antares section) or via env on the agent runner:

| Setting | Values | Notes |
|---------|--------|-------|
| Enable Antares | off / on | Disabled by default |
| Run location | This machine / Another device on network | `ANTARES_BASE_URL` points at a local or LAN OpenAI-compatible endpoint (`/v1/chat/completions`) |
| Model profile | Auto recommended / Antares 350M / Antares 1B / Custom | Auto recommends 350M vs 1B from local Apple Silicon memory (≤8GB → 350M, ≥16GB → 1B); for a remote endpoint it probes `/health` and `/v1/models` and shows a warning if the server doesn't expose model metadata |
| Mode | Advisory / Blocking | Advisory never fails the security gate; blocking fails `security_passed` on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW | Only used in blocking mode |
| Test Antares Connection | — | Checks reachability and available models without running a full review |

Only the **Security** reviewer slot can be set to `antares` — architecture, correctness, performance, and documentation reviewers don't offer it.

- **Review chain:** when the security reviewer is assigned to Antares, `review_chain.py` calls it instead of Claude/Codex/Cursor/Gemini, passes along prior Bandit/Semgrep/JS findings for context, and posts structured findings (severity, file, line, issue, fix) to the WO thread in the normal review format.
- **Quality gate:** `quality_gate.py` can run an optional Antares scan over the changed diff alongside CI/Bandit/Semgrep/JS. It contributes to `finding_count` but only flips `security_passed` to false in blocking mode (or if Antares is required and unreachable) — in advisory mode, findings and errors are visible in the thread but never block.
- Malformed model output or a timeout is treated as a non-blocking scan error in advisory mode; model output is always parsed and validated before it's used in thread messages or gate decisions.

## Relevant WO specs (completed features to document)

- WO-1008 — Cloud Codex (GitHub Actions) dispatch path
- WO-1053 — Antares security reviewer backend
- WO-1082 — `PUT /api/config` allowlist
- WO-1092 — Unique draft ports + one-click product remount