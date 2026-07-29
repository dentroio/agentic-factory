---
title: "Agent Backends"
description: "Configuring and using AI backends (Claude, Cursor, Codex, Gemini, claude-api) for WO execution"
last_verified: 2026-07-29
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

**`codex`** is fast for well-scoped implementation tasks where the spec is highly specific. Less strong on architectural judgment. Codex can also run in GitHub Actions via the cloud agent path (see [Codex GitHub Actions dispatch](#codex-github-actions-dispatch) below).

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

P1 WOs (and optionally P2) require a human approval step before an agent starts working. This prevents agents from running for hours on WOs whose environment prerequisites aren't met.

The dispatch lifecycle for gated WOs is:

```
queue → pending_approval → claimed → in_progress → awaiting_human → complete
```

When a P1 WO reaches the front of the queue, the orchestrator moves it to `pending_approval` and fires a Slack/ntfy notification instead of dispatching immediately. The agent runner receives HTTP 423 (Locked) if it attempts to claim a WO in this state.

**Approvals panel** — The Factory tab shows a **Pending Approval** section (above Active Jobs) whenever approvals are waiting. Each entry shows the WO ID, priority, title, services, and effort. From there you can:

- **View spec** — expands an inline preview of the first 40 lines of the WO spec
- **Approve →** — moves the WO to claimed; an agent picks it up on the next poll cycle
- **Skip** — returns the WO to the queue; it won't re-enter `pending_approval` for 24 hours
- **Hold** — moves the WO to held state

The panel is hidden when no approvals are pending.

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUIRE_APPROVAL_FOR` | `P1` | Comma-separated priorities that require pre-dispatch approval. Set to `P1,P2` to gate both. P3 always dispatches immediately. |

## Domain-scoped agent runners

By default a single runner claims any available WO. When running multiple agents in parallel on the same repo, generalist runners compete for the same files and produce merge conflicts. Domain-scoped runners fix this: each runner instance declares which service domain it owns, and only claims WOs whose `services` field matches.

### DOMAIN_FILTER env var

Set `DOMAIN_FILTER` in the runner's environment:

```
DOMAIN_FILTER=frontend        # only claims WOs with services: frontend
DOMAIN_FILTER=data-service    # only claims WOs with services: data-service
DOMAIN_FILTER=                # claims any WO (default — existing behavior)
```

Matching rule: any token in `DOMAIN_FILTER` appears as a case-insensitive substring of any token in the WO's `services` list. A WO with `services: frontend,data-service` is claimable by either the `frontend` or `data-service` domain runner.

If the WO's services don't match, the runner logs:
```
[runner] WO-NNN services={services} — not in domain {DOMAIN_FILTER}, skipping
```
and moves to the next WO. The claim race resolves conflicts: whichever matching runner calls `/api/claim` first wins.

### Built-in domain plist templates

`agent-install.sh` generates four domain runner LaunchAgent plists alongside the existing generalist plist:

| Label | DOMAIN_FILTER | PREFERRED_AGENT |
|---|---|---|
| `com.dentroio.factory-agent-frontend` | `frontend` | cursor |
| `com.dentroio.factory-agent-data` | `data-service` | cursor |
| `com.dentroio.factory-agent-connector` | `connector-service` | cursor |
| `com.dentroio.factory-agent-docs` | `docs,P3` | cursor |

The `docs` domain runner handles WOs whose services field is `none` or `docs`, or whose priority is `P3`, serializing all docs-only WOs through a single runner.

The existing `com.dentroio.factory-agent-cursor` plist (no domain filter) remains the generalist fallback.

### Status bar

The Factory tab status bar shows active domain labels:
```
● 2 runners online  |  frontend · data  |  3 active
```

## Cross-LLM review

When **Force cross-LLM review** is enabled (default), the reviewer backends are automatically rotated to differ from the coding agent. If Cursor wrote the code and Claude and Codex are both available, the four reviewers get Claude/Codex/Claude/Codex in rotation. This prevents the same model from reviewing its own output.

When the toggle is off, you assign reviewers manually in the per-reviewer dropdowns in **Settings → Agents**.

Change the toggle at any time — it takes effect on the next WO without restarting anything.

## Codex GitHub Actions dispatch

For WOs with `services: none` (docs-only or P3 WOs), you can dispatch Codex to run in GitHub Actions instead of requiring a local agent runner. This is the cloud agent path.

### How it works

Call `POST /api/dispatch-codex`:

```bash
curl -X POST http://localhost:8100/api/dispatch-codex \
  -H "Content-Type: application/json" \
  -d '{"wo":"WO-362","slug":"sync-in-app-help"}'
```

The orchestrator:
1. Checks for an existing claim — returns 409 if already active
2. Pre-claims the WO as `codex-gh-actions / github-actions`
3. POSTs a `workflow_dispatch` event to `codex-dispatch.yml` in the target repo
4. On failure (bad repo, workflow not found), rolls back the claim and returns 502
5. Returns `{"ok": true, "wo": "WO-362", "repo": "...", "agent": "codex-gh-actions"}`

The orchestrator's existing poll loop detects the resulting branch and PR automatically — no callback is needed.

### What the workflow does

The `codex-dispatch.yml` GitHub Actions workflow:

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

**New env var:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CODEX_WORKFLOW_FILE` | `codex-dispatch.yml` | Workflow filename in the target repo |

## Push notifications

The factory fires push notifications through two parallel channels for key events. Configure both, either, or neither — missing credentials are silently skipped.

### ntfy.sh

Lightweight push notifications to iOS, Android, or desktop via the [ntfy app](https://ntfy.sh/).

`make agent-setup` auto-generates a topic in the format `factory-{14 random alphanumeric chars}` (~5 quadrillion combinations) and stores it in the macOS Keychain. You can also configure the topic manually in **Settings → Authentication**:

- **Topic** input + **Generate** button — generates a new random topic
- **Your Topic** — large monospace display with **Copy** button
- **Subscribe URL** — `{server}/{topic}` with **Copy** button
- **Server URL** — override for self-hosted ntfy (default: `https://ntfy.sh`)
- **Test Notification** button — fires a test ping

Self-hosted option:
```bash
docker run -p 8098:80 binwiederhier/ntfy serve
# then set NTFY_SERVER=http://localhost:8098
```

| Variable | Default | Description |
|----------|---------|-------------|
| `NTFY_TOPIC` | _(empty)_ | Topic name — set by `agent-setup` or Settings UI |
| `NTFY_SERVER` | `https://ntfy.sh` | Override for self-hosted ntfy |

### Slack

Create an Incoming Webhook in your Slack workspace and paste the URL into **Settings → Authentication → Slack Webhook URL**. Messages use Block Kit and include WO ID, agent name, thread summary, and a factory dashboard link.

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack Incoming Webhook URL |

### Notification events

| Event | ntfy Priority |
|-------|---------------|
| WO needs human review (quality gate passed) | `high` |
| WO merged / complete | `default` |
| Agent gave up / errored | `high` |
| WO entered `pending_approval` | `high` |
| Dependabot PR merged | `low` |
| Dependabot conflict auto-rebased | `low` |
| Settings test ping | `default` |

All notifications fire as `asyncio.create_task()` — they never block the API response.

### Tab badge

The factory dashboard tab title prefixes the pending validation count when non-zero:

```
(2) AI Factory   ← two WOs awaiting review
AI Factory       ← nothing pending
```

## Slack two-way bot

Beyond one-way Slack notifications, the factory supports a two-way Slack bot for interacting with the PM chat directly from Slack — no browser tab required.

The bot uses Socket Mode (outbound WebSocket — no public URL required) and listens for:
- **`app_mention`** events in channels where the bot is invited (`@factory what's next?`)
- **`message.im`** events in direct messages to the bot

All messages route through the same PM chat logic as the browser interface — same Claude backend, same Dependabot action parsing, same factory context injection. Per-channel conversation history is maintained in memory (last 20 turns; resets on container restart).

While processing, the bot adds a `:thinking_face:` reaction to your message and removes it when the reply is posted.

```
# In a channel (after /invite @factory):
@factory what WOs are ready to start?
@factory approve WO-237

# In a DM to the bot:
what's the current velocity?
are there any Dependabot PRs with conflicts?
```

### Required env vars

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | `xoxb-...` Bot User OAuth Token |
| `SLACK_APP_TOKEN` | `xapp-...` App-Level Token for Socket Mode (`connections:write` scope) |

Both are optional. If either is missing, the bot is silently disabled (no crash, just a log message).

### One-time Slack app setup

> Do this once per workspace. Reuse the Slack app created for Incoming Webhooks if you already set that up.

1. **Enable Socket Mode** — api.slack.com/apps → your app → **Socket Mode** → On → **Generate** App-Level Token with `connections:write` scope → copy `xapp-...` token → set `SLACK_APP_TOKEN`

2. **Add bot event subscriptions** — **Event Subscriptions** → On → Subscribe to bot events: `app_mention`, `message.im`

3. **Add OAuth scopes** — **OAuth & Permissions