---
title: "Agent Backends"
description: "Configuring and using AI backends (Claude, Cursor, Codex, Gemini, claude-api) for WO execution, the Codex GitHub Actions cloud dispatch path, and the Antares security-only reviewer backend"
last_verified: 2026-08-31
covers_wos:
  - WO-1008
  - WO-1036
  - WO-1037
  - WO-1053
doc_owner: factory-team
---

# Agent Backends

The factory supports five AI backends for executing WOs **against the product repo** (`GITHUB_REPO`). Four are subscription CLI tools on your host. One calls the Anthropic API from Docker. Enable only the ones you use — **Settings → Agents → LLM Providers**. A sixth backend, Antares, is a security-only reviewer used exclusively in the peer review chain (see below).

## The five execution backends

| Backend | How it runs | What you need |
|---------|------------|--------------|
| `claude` | `claude --dangerously-skip-permissions` CLI | Claude Pro or Max subscription + CLI logged in |
| `cursor` | `cursor --headless` CLI | Cursor Pro subscription + CLI logged in |
| `codex` | `codex --approval-mode full-auto` CLI | OpenAI Codex subscription |
| `gemini` | `gemini --yolo -p` CLI | Google Gemini Advanced subscription |
| `claude-api` | Anthropic SDK inside Docker | `ANTHROPIC_API_KEY` in the secrets vault |

The subscription backends run on your host machine and use your existing CLI session credentials. Docker never touches those credentials. The draft server on port 8101 is the bridge: the orchestrator calls `http://host.docker.internal:8101/api/draft` and the draft server calls the CLI on the host.

`claude-api` runs inside Docker and calls the Anthropic API directly. It requires `ANTHROPIC_API_KEY` set in **Settings → Authentication**. Use it when you do not have a subscription CLI available or when you want to avoid running the agent-runner process.

You can manage which backends are active in **Settings → Agents → LLM Providers** — each provider has a name, auth type (subscription/API/both), optional API key config, and step-by-step CLI setup instructions. Backends you disable are hidden from the agent dispatch pool, so the orchestrator will never select them when choosing an agent for a WO.

## Cloud dispatch path: Codex via GitHub Actions

For WOs where `services: none` — typically docs-only WOs with no local repo changes needed beyond a PR — the orchestrator can dispatch to GitHub Actions instead of a local agent-runner. This path needs no Docker worktree and no subscription CLI on the host; Codex runs directly inside the Actions runner.

`POST /api/dispatch-codex` (body: `{"wo": "WO-NNN", "repo": "...", "slug": "...", "ref": "main"}`) triggers a `workflow_dispatch` event on the target repo's `codex-dispatch.yml` workflow. That workflow checks out a fresh branch (`wo/{wo_id}-{wo_slug}`), builds a prompt from the WO spec, installs `@openai/codex`, runs `codex exec -p "$PROMPT"`, and opens a PR if Codex made changes. The orchestrator's existing poll loop detects the resulting branch and PR automatically — no callback is required.

The WO is pre-claimed as `codex-gh-actions / github-actions` for the duration; a second dispatch attempt on the same WO returns 409.

Requirements:

| Requirement | Notes |
|-------------|-------|
| `codex-dispatch.yml` workflow file | Must exist in the target repo |
| `OPENAI_API_KEY` | Set as a GitHub Actions secret on the target repo — not the factory secrets vault |
| `GITHUB_TOKEN` | Provided automatically by Actions |
| `CODEX_WORKFLOW_FILE` env var | Optional override for the workflow filename (default `codex-dispatch.yml`) |

This path is selected automatically for `services: none` WOs and complements — it does not replace — the host CLI `codex` backend used for regular WOs with real service changes.

## Security reviewer backend: Antares

Antares (Cisco Foundation AI) is a purpose-built vulnerability-localization model that can be added as an additional **Security reviewer** backend in the peer review chain, alongside the deterministic scanners the factory already runs (Bandit, Semgrep, a JS/TS security scan). It is not a general-purpose coding backend — it is only selectable for the Security reviewer role, and only complements Bandit/Semgrep rather than replacing them.

**Disabled by default, advisory by default.** Antares must be explicitly enabled, and even when enabled it only produces advisory findings unless blocking mode is explicitly configured.

### Configuration

Configure Antares in **Settings → Agents / Reviewer Assignments**:

| Setting | Values |
|---------|--------|
| Enable Antares security reviewer | on/off |
| Run location | This machine, or another device on the LAN |
| Endpoint URL | e.g. `http://localhost:8000` |
| Model profile | Auto recommended, Antares 350M, Antares 1B, Custom |
| Custom model value | GGUF path or model ID, for Custom profile |
| Mode | Advisory or Blocking on configured severities |
| Blocking severities | CRITICAL / HIGH / MEDIUM / LOW (multi-select) |

The corresponding backend env vars:

```text
ANTARES_ENABLED=false
ANTARES_BASE_URL=http://localhost:8000
ANTARES_MODEL=fdtn-ai/antares-350m | fdtn-ai/antares-1b | custom
ANTARES_API_KEY=
ANTARES_TIMEOUT_SECONDS=120
ANTARES_MODE=advisory | blocking
ANTARES_BLOCKING_SEVERITIES=CRITICAL,HIGH
```

Antares talks to an OpenAI-compatible chat completions endpoint (`POST {ANTARES_BASE_URL}/v1/chat/completions`). It never sends source code to a cloud endpoint unless you explicitly point `ANTARES_BASE_URL` at one.

### Model profiles

| Profile | Model | Intended use |
|---------|-------|--------------|
| Auto recommended | `auto` | Factory picks a profile from local hardware, or from the remote `/models` response |
| Antares 350M | `fdtn-ai/antares-350m` | Lower-memory Macs (M1 8GB), CPU-only/shared machines |
| Antares 1B | `fdtn-ai/antares-1b` | M1/M2/M3 16GB+, higher-quality local review |
| Custom | user-supplied | GGUF paths, future Antares releases, remote GPU hosts |

For a local (this-machine) run, the factory recommends 350M on an M1 with ≤8GB RAM, 1B on 16GB+, and falls back to 350M when hardware is unknown. For a network endpoint, the factory probes `GET /health` and `GET /v1/models` on the remote server if available; if the remote doesn't expose model metadata, the UI shows the configured model with a warning that remote hardware suitability can't be verified.

Use **Test Antares Connection** in the settings UI to verify reachability and model availability without running a full review.

### Review chain and quality gate behavior

- When the Security reviewer role is assigned to `antares`, the review chain calls Antares instead of Claude/Codex/Cursor/Gemini for that role, and posts structured findings (severity, file, line, issue, fix) to the WO thread in the normal review-thread format. Prior Bandit/Semgrep/JS findings are included in the Antares prompt so the model can deduplicate or localize related issues.
- The quality gate can also run an optional Antares scan in parallel with CI, Bandit, Semgrep, and the JS security scan, scanning only the changed diff. It returns `antares_findings`, `antares_error`, and `antares_passed`, and adds Antares findings to the overall finding count.
- **Advisory mode** (default when enabled): Antares findings and errors never block `security_passed`. Findings are still visible in the WO thread.
- **Blocking mode**: `security_passed` fails when configured severities (e.g. CRITICAL/HIGH) are found, or when Antares is required but unreachable (fails closed).
- Existing Bandit, Semgrep, JS scan, and the Claude/Codex/Cursor/Gemini reviewer behavior are unchanged when Antares is disabled.

Antares is only offered for the Security reviewer role — architecture, correctness, performance, and documentation reviewer assignments do not offer it.