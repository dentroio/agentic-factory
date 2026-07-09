# WO-1007 — Push Notifications: ntfy.sh + Slack for Factory Events

**Status:** ✅ Complete (extended 2026-07-07)
**Priority:** P1
**Effort:** S (half day initial) + S (full event coverage + Settings UI)
**Services:** orchestrator, status-site
**Depends on:** WO-365

---

## Problem

After an agent completes a WO and calls `/api/validate`, the human operator has
no way to know — unless they happen to be watching the factory dashboard.
Validations could sit unreviewed for hours, blocking the agent loop.

Extended scope: Dependabot PRs could conflict or stall with no visibility.
WO completions and agent errors also needed operator awareness.

---

## What Was Built

### `notifications.py` — orchestrator module

All factory events route through two channels in parallel.

**ntfy.sh** — `_send_ntfy(title, body, priority, tags, secrets)`
- POSTs to `{NTFY_SERVER}/{NTFY_TOPIC}` (server defaults to `https://ntfy.sh`)
- `Title` header is URL-encoded (`urllib.parse.quote`) to support emoji
- `Content-Type: text/plain; charset=utf-8`
- No account required; install the ntfy app and subscribe to your topic URL

**Slack** — `_send_slack(text, blocks, secrets)`
- POSTs a Block Kit message to `SLACK_WEBHOOK_URL`
- Shows WO ID, agent name, thread summary, and a factory dashboard link

Both functions read credentials from the secrets store at call time (`secrets: dict | None = None`), not from stale env vars baked at startup.

**Notification events:**

| Function | Event | ntfy Priority |
|----------|-------|---------------|
| `notify_validation_needed()` | WO needs human review | `high` |
| `notify_wo_complete()` | WO merged / complete | `default` |
| `notify_wo_error()` | Agent gave up / errored | `high` |
| `notify_dependabot("merged")` | Dependabot PR merged | `low` |
| `notify_dependabot("conflict")` | Dependabot conflict auto-rebased | `low` |
| `notify_test()` | Settings test ping | `default` |

### Orchestrator wiring

- `/api/validate` → fires `notify_validation_needed` on quality gate pass
- `/api/complete` → fires `notify_wo_complete`
- Agent error path → fires `notify_wo_error`
- `POST /api/dependabot/prs/{n}/approve-merge` → fires `notify_dependabot("merged")`
- Hourly conflict scan → fires `notify_dependabot("conflict")`
- `POST /api/notifications/test` → calls `notify_test`, raises 422 if topic not configured
- `GET /api/notifications/config` → returns `{"ntfy_topic": "...", "ntfy_server": "..."}` (actual strings, not booleans — needed by Settings UI)

All notifications fire as `asyncio.create_task()` — never block the API response.

### Status site — Settings → Authentication

ntfy section above the Slack section:

- **Topic** input field + **Generate** button
  - Generates `factory-{14 random alphanumeric chars}` using `crypto.getRandomValues()`
  - ~5 quadrillion combinations — effectively unguessable
- **Your Topic** large-font monospace display with **Copy** button
- **Subscribe URL** display (`{server}/{topic}`) with **Copy** button
- Warning: *"contains characters that look similar in some fonts — use the copy button"*
- **Server URL** input (default `https://ntfy.sh`; override for self-hosted)
- **Test Notification** button → `POST /api/factory/notifications/test` → shows inline status

Topic and server values are fetched from `/api/notifications/config` (not `/api/secrets`, which returns booleans only for security).

### Status site proxy routes

```
GET  /api/factory/notifications/test  → POST /api/notifications/test
```

### Tab badge

`base.html` `<title>` prefixes pending validation count when non-zero:

```
(2) AI Factory   ← two WOs awaiting review
AI Factory       ← nothing pending
```

### `agent-setup.sh` — auto-generation

`make agent-setup` no longer prompts for a topic name. Instead:

```bash
NTFY_TOPIC_VAL="factory-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 14)"
```

Displays the generated topic and subscribe URL, stores both `NTFY_TOPIC` and
`NTFY_SERVER` in the macOS Keychain alongside other secrets.

---

## Env Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `NTFY_TOPIC` | _(empty)_ | Topic name — set by `agent-setup` or Settings UI |
| `NTFY_SERVER` | `https://ntfy.sh` | Override to point at a self-hosted ntfy server |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack Incoming Webhook URL |

All three are optional. If empty, the corresponding channel silently skips.

---

## Setup (one-time)

### ntfy.sh (recommended)

1. Run `make agent-setup` — topic is auto-generated and stored
2. Open Settings → Authentication in the factory dashboard
3. Copy the Subscribe URL shown under "Your Topic"
4. Install the [ntfy app](https://ntfy.sh/) on iOS / Android / desktop and subscribe

### ntfy (self-hosted, full privacy)

1. Run `docker run -p 8098:80 binwiederhier/ntfy serve`
2. Set `NTFY_SERVER=http://localhost:8098` and any topic name

### Slack

1. Create an Incoming Webhook in your Slack workspace
2. Paste URL into Settings → Authentication → Slack Webhook URL

---

## Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `/api/validate` (quality gate pass) fires ntfy if topic configured | ✅ |
| 2 | `/api/validate` fires Slack if webhook configured | ✅ |
| 3 | Notification failure never fails the API response | ✅ |
| 4 | Status site tab title shows `(N)` prefix when validations pending | ✅ |
| 5 | No notifications if env vars empty | ✅ |
| 6 | WO complete, agent error, Dependabot events also fire notifications | ✅ |
| 7 | Settings → Authentication shows topic, subscribe URL, test button | ✅ |
| 8 | Topic auto-generated by `agent-setup`; 14-char random alphanumeric | ✅ |
| 9 | Emoji in notification titles does not cause ASCII encoding error | ✅ |
| 10 | Settings displays actual topic string, not Python `True` | ✅ |

---

## Execution

- **Branch:** `wo/366-notification-webhooks` (agentic-factory)
- **Risk tier:** P2 — new module, non-breaking (all env vars default to empty = disabled)
