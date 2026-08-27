---
title: "Agent Backends"
description: "Configuring and using AI backends (Claude, Cursor, Codex, Gemini, claude-api) for WO execution, including the Codex GitHub Actions cloud dispatch path"
last_verified: 2026-08-27
covers_wos:
  - WO-1008
  - WO-1036
  - WO-1037
doc_owner: factory-team
---

# Agent Backends

The factory supports five AI backends for executing WOs. Four are subscription-based CLI tools that run on your host machine. One calls the Anthropic API directly from Docker. Enable only the ones you use — **Settings → Agents → LLM Providers** controls which are active in your factory.

## The five backends

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