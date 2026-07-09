# WO-1015 — Slack Two-Way Bot: PM Chat via Slack Socket Mode

**Status:** ✅ Complete (2026-07-07)
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-1007

---

## Problem

Slack notifications are one-way — the factory alerts you but you can't respond.
The browser PM chat requires opening a dashboard tab. Operators want to ask
the factory PM questions, approve/reject WOs, and trigger Dependabot actions
directly from Slack.

---

## What Was Built

### `slack_bot.py` — new orchestrator module

Uses `slack-sdk` Socket Mode (outbound WebSocket — no public URL required).

**Flow:**
1. On startup the bot connects to Slack's Socket Mode API
2. Listens for `app_mention` events (channel: `@factory hello`) and `message` events (DMs)
3. Strips the `@mention` prefix, maintains per-channel conversation history
4. Calls `POST /api/pm/chat` on the orchestrator itself (self-call via `ORCHESTRATOR_URL`)
5. Adds `:thinking_face:` reaction while processing; removes it when done
6. Posts the PM reply back in the same Slack thread

The bot reuses the full PM chat logic — same Claude backend, same Dependabot
action tag parsing (`[DEPENDABOT:rebase:NNN]`, `[DEPENDABOT:approve-merge:NNN]`),
same factory context injection.

Per-channel history is kept in memory (last 20 turns); resets on container restart.

### Orchestrator wiring

`start_slack_bot()` is called in the FastAPI `lifespan` handler and runs in a
daemon thread. If `SLACK_BOT_TOKEN` or `SLACK_APP_TOKEN` is not set, the function
logs a message and returns `None` — no error, bot simply disabled.

### New env vars

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | `xoxb-...` Bot User OAuth Token |
| `SLACK_APP_TOKEN` | `xapp-...` App-Level Token for Socket Mode (`connections:write` scope) |

Both added to `docker-compose.status.yml` and `.env.example`.

---

## One-Time Slack App Setup

> You only need to do this once per Slack workspace. Uses your existing Slack App
> (created for the Incoming Webhooks in WO-1007).

1. **Enable Socket Mode**
   - api.slack.com/apps → your Factory app → **Socket Mode** → toggle On
   - Click **Generate** to create an App-Level Token
   - Give it the `connections:write` scope
   - Copy the `xapp-...` token → set `SLACK_APP_TOKEN` in your `.env`

2. **Add bot event subscriptions**
   - **Event Subscriptions** → toggle On
   - Under **Subscribe to bot events** add:
     - `app_mention` — so the bot responds when @mentioned in a channel
     - `message.im` — so the bot responds to direct messages

3. **Add OAuth scopes**
   - **OAuth & Permissions** → Bot Token Scopes → Add:
     - `chat:write` — post messages
     - `app_mentions:read` — receive @mentions
     - `im:history` — read DMs
     - `reactions:write` — add/remove :thinking_face: reaction

4. **Reinstall the app**
   - **OAuth & Permissions** → **Reinstall to Workspace**
   - Copy the `xoxb-...` Bot User OAuth Token → set `SLACK_BOT_TOKEN` in your `.env`

5. **Rebuild the orchestrator**
   ```bash
   docker compose -f docker-compose.status.yml build orchestrator
   docker compose -f docker-compose.status.yml up -d orchestrator
   ```

6. **Invite the bot to a channel** (for @mention mode)
   ```
   /invite @YourFactoryBotName
   ```

7. **Test it**
   - DM the bot: `what's the status?`
   - Or in a channel: `@factory what's next?`

---

## Usage Examples

```
# In a channel (after /invite @factory):
@factory what WOs are ready to start?
@factory approve WO-237
@factory rebase PR 278

# In a DM to the bot:
what's the current velocity?
are there any Dependabot PRs with conflicts?
```

The bot routes all messages through the same PM chat logic — it understands
the same context, plans, and actions as the browser chat.

---

## Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Bot starts on orchestrator startup if both tokens are set | ✅ |
| 2 | Bot is silently disabled if tokens not set (no crash) | ✅ |
| 3 | DM to bot gets a PM chat reply in the same thread | ✅ |
| 4 | @mention in a channel gets a PM chat reply in the same thread | ✅ |
| 5 | `:thinking_face:` reaction while processing | ✅ |
| 6 | Conversation history maintained per-channel (last 20 turns) | ✅ |
| 7 | Bot messages do not trigger bot loop | ✅ |
| 8 | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` in docker-compose + .env.example | ✅ |
| 9 | `slack-sdk>=3.27.0` added to orchestrator requirements.txt | ✅ |

---

## Execution

- **Branch:** `wo/374-slack-two-way-bot` (agentic-factory)
- **Risk tier:** P2 — new daemon thread, opt-in via env vars, no API surface change
