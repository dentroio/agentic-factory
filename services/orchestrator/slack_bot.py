"""Slack Socket Mode bot — two-way PM chat with the factory via Slack."""
import logging
import os
import re
import threading
import time

import httpx

logger = logging.getLogger(__name__)

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8100")

# In-memory conversation history keyed by Slack channel ID
_history: dict[str, list[dict]] = {}
_MAX_HISTORY = 20

# Active socket client — replaced on reconnect
_socket_client = None
_socket_lock = threading.Lock()


def _get_tokens(secrets: dict | None = None) -> tuple[str, str]:
    """Return (bot_token, app_token) from secrets store, falling back to env vars."""
    s = secrets or {}
    bot = s.get("SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN", "")
    app = s.get("SLACK_APP_TOKEN") or os.getenv("SLACK_APP_TOKEN", "")
    return bot, app


def _strip_mention(text: str) -> str:
    return re.sub(r"^<@[A-Z0-9]+>\s*", "", text).strip()


def _make_handler(bot_token: str):
    """Return an event handler closure bound to the given bot token."""
    def _handle_event(client, req) -> None:  # type: ignore[no-untyped-def]
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk import WebClient

        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        event = req.payload.get("event", {})
        event_type = event.get("type", "")

        if event_type not in ("app_mention", "message"):
            return
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return
        if event.get("subtype") in ("message_changed", "message_deleted"):
            return

        channel = event.get("channel", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or ts
        text = _strip_mention(event.get("text", "")).strip()

        if not text:
            return

        web = WebClient(token=bot_token)

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

    return _handle_event


def stop_slack_bot() -> None:
    """Disconnect and clear the active socket client."""
    global _socket_client
    with _socket_lock:
        if _socket_client is not None:
            try:
                _socket_client.disconnect()
                logger.info("[slack_bot] disconnected")
            except Exception as e:
                logger.warning("[slack_bot] disconnect error: %s", e)
            _socket_client = None


def start_slack_bot(secrets: dict | None = None) -> bool:
    """Connect the Socket Mode bot using the provided secrets (or env vars).

    Returns True if the bot started, False if tokens are not configured.
    Replaces any existing connection.
    """
    global _socket_client

    bot_token, app_token = _get_tokens(secrets)
    if not bot_token or not app_token:
        logger.info("[slack_bot] tokens not configured — bot disabled")
        return False

    stop_slack_bot()

    def _run() -> None:
        global _socket_client
        try:
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient

            sc = SocketModeClient(
                app_token=app_token,
                web_client=WebClient(token=bot_token),
            )
            sc.socket_mode_request_listeners.append(_make_handler(bot_token))
            sc.connect()

            with _socket_lock:
                _socket_client = sc

            logger.info("[slack_bot] Socket Mode connected — bot ready")
            while sc.is_connected():
                time.sleep(5)
            logger.info("[slack_bot] Socket Mode disconnected")
        except Exception as e:
            logger.error("[slack_bot] fatal error: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="slack-bot")
    t.start()
    return True


def is_connected() -> bool:
    return _socket_client is not None and getattr(_socket_client, "is_connected", lambda: False)()
