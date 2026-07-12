---
title: "Notifications"
description: "Push notification setup via ntfy and Slack for factory lifecycle events"
last_verified: 2026-07-11
covers_wos: []
doc_owner: factory-team
---

# Notifications

The factory sends push notifications for key lifecycle events. Two channels are supported: ntfy (push to phone/desktop) and Slack (webhook to a channel). Both can run simultaneously.

## ntfy setup

[ntfy](https://ntfy.sh) is a free, open-source pub/sub notification service with apps for iOS, Android, desktop (Windows/macOS/Linux), and browser.

**Automatic setup:** Running `make agent-setup` generates a private topic name like `factory-a7k3m9q2x4b8nf` (14 random alphanumeric characters — effectively unguessable) and stores it in your macOS Keychain. The subscribe URL is printed at setup time.

**Subscribing:**
1. Install the ntfy app on your phone or desktop.
2. Add the subscribe URL: `https://ntfy.sh/factory-a7k3m9q2x4b8nf` (your topic shown in Settings → Authentication).
3. Notifications from the factory appear immediately.

**Managing your topic:** Open **Settings → Authentication** → ntfy Push Notifications. You can:
- Copy the subscribe URL with one click
- Click **Generate** to rotate to a new topic (invalidates the old one)
- Click **Send test notification** to verify delivery end-to-end

**Self-hosting ntfy:** If you want full privacy (ntfy.sh topics are public — anyone who knows the topic URL can subscribe), run ntfy locally:

```bash
docker run -p 8098:80 binwiederhier/ntfy serve
```

Then set `NTFY_SERVER=http://localhost:8098` in **Settings → Authentication**.

## ntfy events

| Event | Priority |
|-------|----------|
| WO needs human review (sign-off checkpoint) | High (🔴) — loud alert |
| Agent gave up or errored on a WO | High (🔴) — loud alert |
| WO merged / complete | Default (🟡) |
| Dependabot PR merged | Low (🟢) |
| Dependabot merge conflict auto-rebased | Low (🟢) |

High-priority notifications bypass Do Not Disturb on most devices. Default and low follow your normal notification settings.

## Slack webhook setup

Slack receives the same events as ntfy. Both fire in parallel if configured.

1. In your Slack workspace, create an incoming webhook: [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks)
2. Copy the webhook URL (`https://hooks.slack.com/services/...`)
3. Open **Settings → Authentication** in the dashboard
4. Paste the URL into the Slack Webhook field and save

Slack notifications use Block Kit formatting — the WO title and PR link appear as clickable elements in the message.

## Slack bot (optional)

The factory also supports a conversational two-way Slack bot using Socket Mode. This is separate from the webhook above.

With the bot configured, you can DM it or `@mention` it in any channel and have the same PM chat conversation you would have in the dashboard. WO dispatch, phase creation, PR merging — all from Slack.

Setup requires two tokens from a Slack app you create:
- `SLACK_BOT_TOKEN` (`xoxb-...`) — OAuth token from the app's OAuth page
- `SLACK_APP_TOKEN` (`xapp-...`) — Socket Mode token from the app's "App-Level Tokens" page

Set both in **Settings → Authentication**. The bot starts automatically alongside the orchestrator and is a no-op if either token is absent.

## Testing notifications

The quickest test:

1. Open **Settings → Authentication**
2. Click **Send test notification** under the ntfy section

This calls `POST /api/notifications/test` on the orchestrator, which fires a test ping to both ntfy and Slack if configured.

You can also trigger a real event by holding a WO, dispatching it, and approving the validation request — each transition fires the relevant notification.

## Notification delivery troubleshooting

If notifications are not arriving:

1. Check that `NTFY_TOPIC` is set: the badge in **Settings → Authentication** should show "Set".
2. Send a test notification. If the test fires but lifecycle events do not, check the orchestrator logs: `docker logs factory-orchestrator`.
3. If you are self-hosting ntfy, confirm the container is reachable from the orchestrator container: the `NTFY_SERVER` value must be accessible from inside Docker (use `http://host.docker.internal:8098` on macOS, not `http://localhost:8098`).
4. For Slack, verify the webhook URL is still valid in your Slack workspace settings.
