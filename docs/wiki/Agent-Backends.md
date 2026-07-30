---
title: "Agent Backends"
description: "Configuring and using AI backends (Claude, Cursor, Codex, Gemini, claude-api) for WO execution"
last_verified: 2026-07-30
covers_wos:
  - WO-1007
  - WO-1008
  - WO-1015
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

You can manage which backends are active in **Settings → Agents → LLM Providers** — each provider has a name, auth type (subscription/API/both), optional API key config, and step-by-step CLI setup instructions. Backends you disable are hidden from the factory UI without affecting the underlying code.

## When to use each

**`claude`** is the most capable for complex reasoning, multi-file refactors, and anything requiring careful analysis of architecture constraints. Best default.

**`cursor`** is strong for IDE-style code generation, especially in projects with large type trees or complex build setups. Good for TypeScript/React heavy work.

**`codex`** is fast for well-scoped implementation tasks where the spec is highly specific. Less strong on architectural judgment. Also used in the cloud agent path (GitHub Actions) for `services: none` / docs-only WOs — see [Cloud agent path (Codex + GitHub Actions)](#cloud-agent-path-codex--github-actions) below.

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

## Pre-dispatch approval

P1 WOs (and optionally P2) go through a mandatory approval step before an agent is assigned. This prevents agents from starting work on WOs whose environment prerequisites aren't met.

### Dispatch lifecycle

```
queue → [pending_approval] → claimed → in_progress → awaiting_human → complete
```

P2 and P3 WOs bypass approval and dispatch immediately.

### Configuring which priorities require approval

Set the `REQUIRE_APPROVAL_FOR` env var (default: `P1`). Accepts a comma-separated list:

```bash
REQUIRE_APPROVAL_FOR=P1        # default — only P1 gated
REQUIRE_APPROVAL_FOR=P1,P2     # gate both P1 and P2
```

### Approving WOs

When a WO enters `pending_approval`, the factory sends a Slack/ntfy notification and the Factory tab shows an **Approvals** panel above Active Jobs:

```
┌─ PENDING APPROVAL ──────────────────────────────────────────── 1 ─┐
│  WO-1036  P1  Pre-Dispatch WO Approval                             │
│  services: orchestrator, status-site  |  effort: M                 │
│  [View spec]  [Approve →]  [Skip]  [Hold]                          │
└────────────────────────────────────────────────────────────────────┘
```

**View spec** expands an inline markdown preview (first 40 lines) without leaving the Factory tab. The panel is hidden when there are no pending approvals.

### Approval API

| Endpoint | Action |
|----------|--------|
| `GET /api/approvals` | List WOs pending approval |
| `POST /api/approvals/{wo_id}/approve` | Dispatch to next available agent |
| `POST /api/approvals/{wo_id}/skip` | Return to queue; won't re-enter pending_approval for 24 h |
| `POST /api/approvals/{wo_id}/hold` | Move to held state |

## Domain-scoped agent runners

Running multiple agents in parallel on the same repo can cause merge conflicts. Domain-scoped runners solve this: each runner instance declares which service domain it owns, and only claims WOs whose `services` field matches.

### DOMAIN_FILTER env var

Set `DOMAIN_FILTER` in the runner's environment:

```bash
DOMAIN_FILTER=frontend          # claims WOs with services: frontend
DOMAIN_FILTER=connector-service # claims WOs with services: connector-service
DOMAIN_FILTER=                  # empty = generalist, claims any WO (default)
```

**Matching rule:** any token in `DOMAIN_FILTER` appears as a case-insensitive substring of any token in the WO's `services` list. A WO with `services: frontend,data-service` is claimable by either a `frontend` or `data-service` domain runner.

When a WO's services don't match, the runner logs:
```
[runner] WO-NNN services={services} — not in domain {DOMAIN_FILTER}, skipping
```

### Built-in domain plist templates

`agent-install.sh` generates four domain-specific LaunchAgent plists alongside the generalist runner:

| Label | DOMAIN_FILTER | PREFERRED_AGENT |
|---|---|---|
| `com.dentroio.factory-agent-frontend` | `frontend` | cursor |
| `com.dentroio.factory-agent-data` | `data-service` | cursor |
| `com.dentroio.factory-agent-connector` | `connector-service` | cursor |
| `com.dentroio.factory-agent-docs` | `docs,P3` | cursor |

The `docs` domain runner matches WOs whose `services` field is `none` or `docs`, or whose priority is `P3`, serializing all docs-only WOs through a single runner. The existing generalist plist (no `DOMAIN_FILTER`) is the fallback when no domain runner is available.

### Status bar

The Factory tab status bar shows active domain labels instead of just the backend name:

```
● 2 runners online  |  frontend · data  |  3 active
```

## Cloud agent path (Codex + GitHub Actions)

P3 and `services: none` WOs (docs-only) can be dispatched to GitHub Actions instead of a local runner. Codex runs in CI — no local Docker, no worktree required.

### How it works

`POST /api/dispatch-codex` triggers a `workflow_dispatch` event on the target repo:

```bash
curl -X POST http://localhost:8100/api/dispatch-codex \
  -H "Content-Type: application/json" \
  -d '{"wo":"WO-362","repo":"dentroio/clarion","ref":"main","slug":"sync-in-app-help"}'
```

The orchestrator:
1. Checks for an existing claim — returns 409 if already active
2. Pre-claims the WO as `codex-gh-actions / github-actions`
3. Triggers `workflow_dispatch`; on failure rolls back the claim and returns 502
4. Returns `{"ok": true, "wo": "WO-362", "repo": "...", "agent": "codex-gh-actions"}`

The orchestrator's existing poll loop detects the resulting branch and PR automatically — no callback needed.

### GitHub Actions workflow (`codex-dispatch.yml`)

The workflow runs these steps in order:

| Step | What happens |
|------|-------------|
| Checkout + git config | Fresh clone, authorship as "Factory Codex" |
| Create branch | `wo/{wo_id}-{wo_slug}` |
| Fetch WO + build prompt | Fetches WO markdown via GitHub API, adds quality mandate |
| Install Codex | `npm install -g @openai/codex` |
| Run Codex | `codex exec -p "$PROMPT"` |
| Detect changes | `git diff --cached` after `git add -A` |
| Commit + push | Only if Codex made changes |
| Open PR | `gh pr create` with WO reference in title and body |

**Required secrets in the target repo:**
- `OPENAI_API_KEY` — for Codex
- `GITHUB_TOKEN` — provided automatically by Actions

### New env var

| Variable | Default | Description |
|----------|---------|-------------|
| `CODEX_WORKFLOW_FILE` | `codex-dispatch.yml` | Workflow filename in the target repo |

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

## Push notifications

The factory sends push notifications for key events via ntfy.sh and/or Slack. Configure both in **Settings → Authentication**.

### ntfy.sh setup

1. Run `make agent-setup` — a topic is auto-generated (`factory-{14 random alphanumeric chars}`) and stored in the macOS Keychain.
2. Open **Settings → Authentication** → copy the Subscribe URL shown under "Your Topic".
3. Install the [ntfy app](https://ntfy.sh/) and subscribe to that URL.

To use a self-hosted ntfy server, set `NTFY_SERVER=http://your-server:port` and any topic name.

### Slack Incoming Webhook setup

1. Create an Incoming Webhook in your Slack workspace.
2. Paste the URL into **Settings → Authentication → Slack Webhook URL**.

### Notification events

| Event | ntfy priority |
|-------|---------------|
| WO needs human review (quality gate passed) | high |
| WO merged / complete | default |
| Agent error | high |
| WO entered `pending_approval` | high |
| Dependabot PR merged | low |
| Dependabot conflict auto-rebased | low |

Notifications fire asynchronously and never block API responses. Both channels are optional — if the env var is empty, that channel silently skips.

### Env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `NTFY_TOPIC` | _(empty)_ | Topic name — set by `agent-setup` or Settings UI |
| `NTFY_SERVER` | `https://ntfy.sh` | Override for a self-hosted ntfy server |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack Incoming Webhook URL |

## Slack two-way bot

In addition to one-way Slack notifications, the factory supports a two-way Slack bot via Socket Mode. You can ask the PM questions, approve/reject WOs, and trigger Dependabot actions directly from Slack — without opening the dashboard.

### How it works

The bot (`slack_bot.py`) connects to Slack's Socket Mode API (outbound WebSocket — no public URL required). It listens for `app_mention` events in channels and `message` events in DMs. Messages are routed through the same PM chat logic as the browser interface — same Claude backend, same Dependabot action parsing, same factory context.

The bot adds a `:thinking_face:` reaction while processing and removes it when done. Per-channel conversation history is kept in memory (last 20 turns); it resets on container restart.

`start_slack_bot()` is called in the FastAPI `lifespan` handler and runs in a daemon thread. If `SLACK_BOT_TOKEN` or `SLACK_APP_TOKEN` is not set, the bot is silently disabled — no error.

### Usage

```
# In a channel (after /invite @factory):
@factory what WOs are ready to start?
@factory approve WO-237
@factory rebase PR 278

# In a DM to the bot:
what's the current velocity?
are there any Dependabot PRs with conflicts?
```

### Setup (one-time)

> Uses your existing Slack App (created for Incoming Webhooks). You only need to do this once per workspace.

1. **Enable Socket Mode** — api.slack.com/apps → your Factory app → **Socket Mode** → toggle On → **Generate** an App-Level Token with the `connections:write` scope → copy the `xapp-...