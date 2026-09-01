---
title: "Agent Backends"
description: "Claude, Cursor, Codex, Gemini, claude-api, cloud Codex dispatch, and Antares security review"
last_verified: 2026-09-01
covers_wos:
  - WO-1008
  - WO-1053
  - WO-1082
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

Subscription CLIs use **host** login cookies/tokens — Docker never mounts them. The draft server (`:8101`) bridges orchestrator → host CLI.

Disable unused providers so dispatch never selects them. Preferred backend: **Settings → Agents** (also in `~/.config/factory-agent/prefs`).

`PUT /api/config` (the endpoint Settings → Agents writes to) validates every update against an allowlist: `preferred` and each reviewer slot must be one of `claude` / `cursor` / `codex` / `gemini` (plus `antares` for the security reviewer only), `timeout` must fall in a bounded range, and unknown keys are rejected with `400` rather than silently persisted. `automation_model` is not part of this endpoint — it's set via `/api/settings/automation-model`.

## Host runner vs API-only

| Mode | When |
|------|------|
| `make agent-install` / `agent-run` | Normal path for Claude/Cursor/Codex/Gemini on the product clone |
| `claude-api` only | No host CLI; still needs product checkout for real code WOs |

If the dashboard shows WOs but host backends never claim, fix `LOCAL_REPO_PATH` first ([Troubleshooting](Troubleshooting)).

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

Optional Cisco Foundation AI reviewer — **not** a coding backend. Disabled and advisory by default. Configure under **Settings → Agents / Reviewer Assignments**.

| Setting | Typical |
|---------|---------|
| Endpoint | `http://localhost:8000` (OpenAI-compatible `/v1/chat/completions`) |
| Mode | Advisory (never blocks) or Blocking on chosen severities |
| Profiles | 350M / 1B / custom GGUF |

Only the **Security** reviewer role can select `antares` — architecture, correctness, performance, and documentation reviewers do not offer it. Findings are posted to the WO thread in the existing review-thread format alongside Bandit/Semgrep/JS scan results; in advisory mode Antares never fails the security gate, in blocking mode configured severities (e.g. `CRITICAL,HIGH`) fail `security_passed`, and an unreachable/required Antares fails closed.

Use **Test Antares Connection** before relying on it — it checks endpoint reachability and, if the server exposes `/health` or `/v1/models`, available models. Bandit/Semgrep/JS scans still run; Antares does not replace them.

Env vars (when not using UI): `ANTARES_ENABLED`, `ANTARES_BASE_URL`, `ANTARES_MODEL`, `ANTARES_API_KEY`, `ANTARES_TIMEOUT_SECONDS`, `ANTARES_MODE`, `ANTARES_BLOCKING_SEVERITIES`.

## Related

- [Getting Started](Getting-Started) — install runner  
- [Product Profile](Product-Profile) — what agents verify  
- [Daily Workflow](Daily-Workflow) — dispatch and checkpoint