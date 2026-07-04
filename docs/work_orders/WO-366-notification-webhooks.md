# WO-366 — Notification Webhooks: Alert Humans When Approval Is Needed

**Status:** ✅ Complete
**Priority:** P1
**Effort:** S (half day)
**Services:** orchestrator, status-site
**Depends on:** WO-365

---

## Problem

After an agent completes a WO and calls `/api/validate`, the human operator has
no way to know — unless they happen to be watching the factory dashboard.
Validations could sit unreviewed for hours, blocking the agent loop.

---

## What Was Done

### `notifications.py` — new module in `services/orchestrator/`

Two async dispatch functions:

**ntfy.sh** — `_send_ntfy(title, body, priority, tags)`
- POSTs to `https://ntfy.sh/{NTFY_TOPIC}` (or a self-hosted server via `NTFY_SERVER`)
- No account required; install the ntfy app on your phone and subscribe to your topic
- Priority: `high`; tags: `robot,eyes`

**Slack** — `_send_slack(text, blocks)`
- POSTs a rich Block Kit message to `SLACK_WEBHOOK_URL`
- Shows WO ID, agent name, thread summary, and a factory link in one card

`notify_validation_needed(wo_id, agent, title, verify_url, thread_summary)` fires both in sequence.

### Orchestrator — fire notifications on `/api/validate`

After the quality gate passes and the validation record is stored, a
`asyncio.create_task()` fires the notification as a non-blocking background task:

```python
asyncio.create_task(notify_validation_needed(
    wo_id=req.wo,
    agent=req.agent,
    verify_url=req.verify_url,
    thread_summary=req.thread_summary,
))
```

If ntfy or Slack fails, it logs the error and continues — notifications are
best-effort and never block the API response.

### Status site — tab badge

`base.html` `<title>` now prefixes the pending count when validations exist:

```
(2) AI Factory   ← two WOs awaiting review
AI Factory       ← nothing pending
```

Works in any browser tab without JavaScript — rendered server-side by Jinja2.

### New env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `NTFY_TOPIC` | _(empty)_ | Topic name on ntfy.sh (e.g. `my-factory`) |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server URL (override for self-hosted) |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack Incoming Webhook URL |

All three added to `docker-compose.status.yml` orchestrator env and `.env.example`.

---

## Setup (one-time)

### ntfy.sh

1. Install [ntfy app](https://ntfy.sh/) on your phone
2. Subscribe to a topic — pick any unique name, e.g. `clarion-factory-sgerhart`
3. Set `NTFY_TOPIC=clarion-factory-sgerhart` in your `.env`

### Slack

1. Create an Incoming Webhook in your Slack workspace
2. Set `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...` in your `.env`

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `POST /api/validate` (quality gate passed) fires ntfy if `NTFY_TOPIC` set |
| 2 | `POST /api/validate` (quality gate passed) fires Slack if `SLACK_WEBHOOK_URL` set |
| 3 | Notification failure does not fail the API response |
| 4 | Status site tab title shows `(N)` prefix when validations pending |
| 5 | No notifications fire if env vars are empty |

---

## Execution

- **Branch:** `wo/366-notification-webhooks` (agentic-factory)
- **Risk tier:** P2 — new module, non-breaking (all env vars default to empty = disabled)
