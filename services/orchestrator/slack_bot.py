"""Slack Socket Mode bot — two-way PM chat with the factory via Slack."""
import logging
import os
import re
import threading
import time

import httpx

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
# Self-reference so the bot can call the orchestrator's own PM chat endpoint
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8100")

# In-memory conversation history keyed by Slack channel ID
_history: dict[str, list[dict]] = {}
_MAX_HISTORY = 20


def _strip_mention(text: str) -> str:
    return re.sub(r"^<@[A-Z0-9]+>\s*", "", text).strip()


def _handle_event(client, req) -> None:  # type: ignore[no-untyped-def]
    """Process incoming Slack Socket Mode events."""
    from slack_sdk.socket_mode.response import SocketModeResponse

    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

    event = req.payload.get("event", {})
    event_type = event.get("type", "")

    if event_type not in ("app_mention", "message"):
        return
    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return
    # Ignore message edits / deletes
    if event.get("subtype") in ("message_changed", "message_deleted"):
        return

    channel = event.get("channel", "")
    ts = event.get("ts", "")
    thread_ts = event.get("thread_ts") or ts
    text = _strip_mention(event.get("text", "")).strip()

    if not text:
        return

    from slack_sdk import WebClient
    web = WebClient(token=SLACK_BOT_TOKEN)

    # Add a :thinking_face: reaction while the PM processes
    try:
        web.reactions_add(channel=channel, name="thinking_face", timestamp=ts)
    except Exception:
        pass

    history = _history.get(channel, [])
    reply = ":warning: Factory error — no response from orchestrator."

    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/api/pm/chat",
            json={"message": text, "history": history[-_MAX_HISTORY:]},
            timeout=120,
        )
        resp.raise_for_status()
        reply = resp.json().get("reply", reply)

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        _history[channel] = history[-_MAX_HISTORY:]
    except Exception as e:
        logger.error("[slack_bot] pm/chat error: %s", e)
        reply = f":warning: Factory error: {e}"
    finally:
        try:
            web.reactions_remove(channel=channel, name="thinking_face", timestamp=ts)
        except Exception:
            pass

    try:
        web.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=reply,
            mrkdwn=True,
        )
    except Exception as e:
        logger.error("[slack_bot] chat_postMessage error: %s", e)


def start_slack_bot() -> threading.Thread | None:
    """Start the Socket Mode bot in a daemon thread. Returns None if not configured."""
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        logger.info("[slack_bot] SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — bot disabled")
        return None

    def _run() -> None:
        try:
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient

            socket_client = SocketModeClient(
                app_token=SLACK_APP_TOKEN,
                web_client=WebClient(token=SLACK_BOT_TOKEN),
            )
            socket_client.socket_mode_request_listeners.append(_handle_event)
            socket_client.connect()
            logger.info("[slack_bot] Socket Mode connected — bot ready")
            while True:
                time.sleep(30)
        except Exception as e:
            logger.error("[slack_bot] fatal error: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="slack-bot")
    t.start()
    return t
