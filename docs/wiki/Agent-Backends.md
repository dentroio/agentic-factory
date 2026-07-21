---
title: "Agent Backends"
description: "Configuring and using AI backends (Claude, Cursor, Codex, Gemini, claude-api) for WO execution"
last_verified: 2026-07-21
covers_wos: []
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

You can manage which backends are active in **Settings → Agents → LLM Providers** — each provider has a name, auth type (subscription/API/both), optional API key config, and step-by-step CLI setup instructions. Backends you disable are hidden from the factory UI without affecting the underlying code.

## When to use each

**`claude`** is the most capable for complex reasoning, multi-file refactors, and anything requiring careful analysis of architecture constraints. Best default.

**`cursor`** is strong for IDE-style code generation, especially in projects with large type trees or complex build setups. Good for TypeScript/React heavy work.

**`codex`** is fast for well-scoped implementation tasks where the spec is highly specific. Less strong on architectural judgment.

**`gemini`** offers a large context window. Useful when WO specs reference a lot of existing code or documentation that needs to be held in context simultaneously.

**`claude-api`** is the no-runner fallback. It does not run autonomously in an agentic loop — it generates a WO spec draft but cannot claim and implement a WO end-to-end. Use it when the agent-runner is not available.

## How the agent runner works

The agent runner is a host process (not Docker). Start it with `make agent-run`.

For each WO, the runner executes this sequence:

**1. Claim** — fetches the next available WO from `/api/next`, creates a `docs/factory/runs/WO-NNN.json` claim file in the repo (atomic git lock — prevents two agents from claiming the same WO), and marks the WO as `in_progress`.

**2. Fetch spec** — reads the WO markdown file from the repository.

**3. Build prompt** — assembles a prompt from: the Quality and Security Mandate, the project-specific process section (from `AGENT_PROCESS.md`), factory API instructions (how to call `/api/validate`), and the WO spec itself.

**4. Execute** — calls `backend.run(prompt, worktree)`. This is the agentic phase: the AI reads code, creates files, runs commands, and modifies the codebase. Output streams to the WO thread.

**5. Quality gate** — when the agent calls `POST /api/validate`, four checks run in parallel: `make ci-local`, bandit (Python SAST), semgrep (multi-language SAST), and a JS/TS security scan. If any check fails, the validate call is rejected (HTTP 422) and the agent must fix the issues before retrying.

**6. Peer review chain** — once the quality gate passes, four AI reviewers run sequentially. Each reviewer receives the WO spec, the full git diff, and findings from previous reviewers:

| Reviewer | Blocks on |
|----------|-----------|
| Security | CRITICAL, HIGH |
| Architecture | CRITICAL |
| Correctness | CRITICAL, HIGH |
| Performance | CRITICAL |
| Documentation | HIGH (only runs when the WO has a Documentation Required section) |

If any reviewer hits its blocking threshold, the chain stops and the agent is sent back to fix the issues. The documentation reviewer is skipped entirely if the WO has no Documentation Required section.

**7. Human checkpoint** — after all reviewers sign off, the orchestrator queues the WO for human review and sends a high-priority push notification. You verify and approve (or reject with feedback).

**8. PR and merge** — after approval, the agent commits, opens a PR, sets `--auto-merge` if P2, and calls `POST /api/complete`.

## Cross-LLM review

When **Force cross-LLM review** is enabled (default), the reviewer backends are automatically rotated to differ from the coding agent. If Cursor wrote the code and Claude and Codex are both available, the four reviewers get Claude/Codex/Claude/Codex in rotation. This prevents the same model from reviewing its own output.

When the toggle is off, you assign reviewers manually in the per-reviewer dropdowns in **Settings → Agents**.

Change the toggle at any time — it takes effect on the next WO without restarting anything.

## The draft server

The draft server is a lightweight HTTP daemon (`draft_server.py`) that runs as part of the agent-runner process on port 8101. It handles three things:

- **Backend probing** — reports which CLI backends are installed and available. The New WO form uses this to show/hide backend options.
- **WO spec drafting** — the orchestrator proxies `/api/plan/draft` requests here for subscription backends.
- **Dispatch waking** — the PM chat's dispatch action calls `/dispatch` on the draft server to wake the runner immediately instead of waiting for the next poll interval.

If the agent-runner is not running, the draft server is offline, subscription backends show as unavailable in the New WO form, and the PM cannot dispatch to subscription backends.
