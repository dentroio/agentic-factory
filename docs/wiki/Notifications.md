---
title: "Notifications"
description: "ntfy and Slack alerts for product WO lifecycle events from the engine"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Notifications

The **engine** can push when product Work Orders need you, fail, or finish. Channels: **ntfy** (phone/desktop) and **Slack** (webhook and/or bot). Both can run together.

## ntfy

[ntfy](https://ntfy.sh) is open-source pub/sub with mobile and desktop apps.

1. `make agent-setup` creates a long random topic and stores it (Keychain on macOS).  
2. Install the app → subscribe to the URL shown in **Settings → Authentication**.  
3. **Copy** / **Generate** (rotates topic) / **Send test** on that page.

**Self-host:**

```bash
docker run -p 8098:80 binwiederhier/ntfy serve
```

Set `NTFY_SERVER` in Settings. From Docker on macOS use `http://host.docker.internal:8098`, not `localhost`.

Public ntfy.sh topics are guessable only if the URL leaks — treat the topic like a secret.

## Events (ntfy priority)

| Event | Priority |
|-------|----------|
| Human review / sign-off needed | High |
| Agent gave up or errored | High |
| WO merged / complete | Default |
| Dependabot merged / auto-rebase | Low |

High may bypass DND depending on the OS/app.

## Slack webhook

Same events as ntfy when configured:

1. Create an [incoming webhook](https://api.slack.com/messaging/webhooks)  
2. Paste into **Settings → Authentication**  

Messages use Block Kit (WO title, links).

## Slack bot (optional)

Socket Mode bot for two-way PM-style chat from Slack (`SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`). Starts with the orchestrator; no-op if tokens missing.

## Test and troubleshoot

**Settings → Authentication → Send test notification** → `POST /api/notifications/test`.

If silent:

1. ntfy badge must show Set  
2. `docker logs factory-orchestrator` after a test  
3. Self-hosted: orchestrator container must reach `NTFY_SERVER`  
4. Slack: webhook still valid in the workspace  

Lifecycle fire test: hold → dispatch → approve validation.
