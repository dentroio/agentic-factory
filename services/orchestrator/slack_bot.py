"""Slack Socket Mode bot — two-way PM chat with the factory via Slack."""
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8100")
_STATE_PATH = Path("/data/slack_state.json")
_MAX_HISTORY = 20
_MAX_THREADS = 100
_MAX_TURNS = 50

# In-memory conversation history keyed by thread_ts (or channel for DMs)
_history: dict[str, list[dict]] = {}

# Threads the bot has already replied in — used to pick up follow-ups without @mention
_active_threads: set[str] = set()

# Active socket client — replaced on reconnect
_socket_client = None
_socket_lock = threading.Lock()
_state_lock = threading.Lock()


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_state() -> None:
    try:
        with _state_lock:
            threads = list(_active_threads)[-_MAX_THREADS:]
            history_trimmed = {
                k: v[-_MAX_TURNS:] for k, v in list(_history.items())[-_MAX_THREADS:]
            }
            data = {"history": history_trimmed, "active_threads": threads}
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(data))
    except Exception as e:
        logger.warning("[slack_bot] state save failed: %s", e)


def _load_state() -> None:
    global _history, _active_threads
    if not _STATE_PATH.exists():
        return
    try:
        data = json.loads(_STATE_PATH.read_text())
        with _state_lock:
            _history = data.get("history", {})
            _active_threads = set(data.get("active_threads", []))
        logger.info("[slack_bot] state loaded: %d threads, %d active", len(_history), len(_active_threads))
    except Exception as e:
        logger.warning("[slack_bot] state load failed (starting fresh): %s", e)


# ── Block Kit helpers ─────────────────────────────────────────────────────────

# Detects lines like "- WO-185: Syslog Collector [P1]" or "WO-185: Title [P1]"
_WO_LINE_RE = re.compile(
    r"[-*]?\s*(WO-(\d+)):\s*([^\[]+?)(?:\s*\[([^\]]+)\])?\s*$",
    re.MULTILINE,
)

# Detects "Want me to [re-]dispatch WO-NNN / it" + optional backend
_DISPATCH_OFFER_RE = re.compile(
    r"(?:want me to|should i|shall i|ready to)\s+(?:re-?)?(?:dispatch|start|run|kick off)\s+"
    r"(WO-\d+|it|this one|that one)(?:\s+(?:to|with|using|via)\s+([\w-]+))?",
    re.IGNORECASE,
)


def _wo_list_blocks(text: str) -> list[dict] | None:
    """Return Block Kit blocks if the reply contains a formatted WO list."""
    matches = list(_WO_LINE_RE.finditer(text))
    if len(matches) < 2:
        return None

    # Split reply into the preamble (before first WO line) and WO list
    first_start = matches[0].start()
    preamble = text[:first_start].strip()

    blocks: list[dict] = []
    if preamble:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": preamble}})
    blocks.append({"type": "divider"})

    for m in matches:
        wo_id = m.group(1)        # e.g. WO-185
        title = m.group(3).strip()
        meta = m.group(4) or ""   # e.g. P1 · S

        label = f"*{wo_id}*: {title}"
        if meta:
            label += f"  _{meta}_"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": label},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "▶ Dispatch", "emoji": True},
                "action_id": f"dispatch_yes:{wo_id}:claude",
                "style": "primary",
                "value": f"{wo_id}:claude",
            },
        })

    blocks.append({"type": "divider"})
    return blocks


def _dispatch_offer_blocks(text: str) -> list[dict] | None:
    """Return Block Kit blocks with ✅/❌ buttons if the reply is a dispatch offer."""
    m = _DISPATCH_OFFER_RE.search(text)
    if not m:
        return None

    raw_wo = m.group(1)
    backend = (m.group(2) or "claude").lower()

    # Resolve pronouns — scan the full reply for the most recent WO-NNN mention
    if raw_wo.lower() in ("it", "this one", "that one"):
        wo_nums = re.findall(r"\bWO-(\d+)\b", text, re.IGNORECASE)
        if not wo_nums:
            return None
        wo_id = f"WO-{wo_nums[-1]}"
    else:
        wo_id = raw_wo.upper()

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Yes, dispatch", "emoji": True},
                    "style": "primary",
                    "action_id": f"dispatch_yes:{wo_id}:{backend}",
                    "value": f"{wo_id}:{backend}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Not yet", "emoji": True},
                    "action_id": "dispatch_no",
                    "value": "dismiss",
                },
            ],
        },
    ]
    return blocks


def _build_blocks(text: str) -> list[dict] | None:
    """Try to convert a PM reply to Block Kit blocks. Returns None for plain text replies."""
    return _wo_list_blocks(text) or _dispatch_offer_blocks(text)


# ── Event handlers ────────────────────────────────────────────────────────────

def _strip_mention(text: str) -> str:
    return re.sub(r"^<@[A-Z0-9]+>\s*", "", text).strip()


def _get_tokens(secrets: dict | None = None) -> tuple[str, str]:
    s = secrets or {}
    bot = s.get("SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN", "")
    app = s.get("SLACK_APP_TOKEN") or os.getenv("SLACK_APP_TOKEN", "")
    return bot, app


def _make_handler(bot_token: str):
    """Return a Socket Mode request handler closure for all payload types."""

    def _handle(client, req) -> None:  # type: ignore[no-untyped-def]
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk import WebClient

        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        # ── Block Kit button clicks ───────────────────────────────────────────
        if req.type == "interactive":
            payload = req.payload
            if payload.get("type") != "block_actions":
                return
            actions = payload.get("actions", [])
            if not actions:
                return

            action = actions[0]
            action_id: str = action.get("action_id", "")
            channel = payload.get("channel", {}).get("id", "")
            message_ts = payload.get("message", {}).get("ts", "")
            thread_ts = payload.get("message", {}).get("thread_ts") or message_ts
            web = WebClient(token=bot_token)

            if action_id == "dispatch_no":
                try:
                    web.chat_update(
                        channel=channel,
                        ts=message_ts,
                        text="_Dismissed._",
                        blocks=[],
                    )
                except Exception as e:
                    logger.warning("[slack_bot] dismiss update failed: %s", e)
                return

            if action_id.startswith("dispatch_yes:"):
                parts = action_id.split(":", 2)
                wo_id = parts[1] if len(parts) > 1 else "WO-?"
                backend = parts[2] if len(parts) > 2 else "claude"

                # Trigger dispatch via PM chat — this fires [DISPATCH:...] tag processing
                history_key = thread_ts
                history = _history.get(history_key, [])
                confirm_msg = f"Yes, dispatch {wo_id} to {backend}"
                try:
                    resp = httpx.post(
                        f"{ORCHESTRATOR_URL}/api/pm/chat",
                        json={"message": confirm_msg, "history": history[-_MAX_HISTORY:]},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    reply = resp.json().get("reply", f"✅ {wo_id} dispatched to {backend}.")
                    history.append({"role": "user", "content": confirm_msg})
                    history.append({"role": "assistant", "content": reply})
                    with _state_lock:
                        _history[history_key] = history[-_MAX_HISTORY:]
                    _save_state()
                except Exception as e:
                    reply = f"⚠️ Dispatch failed: {e}"

                # Replace the button message with the result
                try:
                    web.chat_update(channel=channel, ts=message_ts, text=reply, blocks=[])
                except Exception:
                    pass
                return

        # ── Regular messages / @mentions ─────────────────────────────────────
        if req.type != "events_api":
            return

        event = req.payload.get("event", {})
        event_type = event.get("type", "")

        if event_type not in ("app_mention", "message"):
            return
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return
        if event.get("subtype") in ("message_changed", "message_deleted"):
            return

        channel = event.get("channel", "")
        channel_type = event.get("channel_type", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or (ts if channel_type == "im" else None)
        text = _strip_mention(event.get("text", "")).strip()

        if not text:
            return

        is_dm = channel_type == "im"
        is_channel = channel_type in ("channel", "group") or event_type == "app_mention"
        is_thread_followup = bool(event.get("thread_ts")) and event.get("thread_ts") in _active_threads
        if not (is_dm or is_channel or is_thread_followup):
            return

        web = WebClient(token=bot_token)

        try:
            web.reactions_add(channel=channel, name="thinking_face", timestamp=ts)
        except Exception:
            pass

        history_key = thread_ts or ts
        history = _history.get(history_key, [])
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
            with _state_lock:
                _history[history_key] = history[-_MAX_HISTORY:]
        except Exception as e:
            logger.error("[slack_bot] pm/chat error: %s", e)
            reply = f":warning: Factory error: {e}"
        finally:
            try:
                web.reactions_remove(channel=channel, name="thinking_face", timestamp=ts)
            except Exception:
                pass

        try:
            blocks = _build_blocks(reply)
            msg_kwargs: dict = {
                "channel": channel,
                "text": reply,   # plain-text fallback (always required)
                "mrkdwn": True,
            }
            if blocks:
                msg_kwargs["blocks"] = blocks
            if thread_ts:
                msg_kwargs["thread_ts"] = thread_ts

            resp = web.chat_postMessage(**msg_kwargs)
            with _state_lock:
                _active_threads.add(ts)
                if resp and resp.get("ts"):
                    _active_threads.add(resp["ts"])
            _save_state()
        except Exception as e:
            logger.error("[slack_bot] chat_postMessage error: %s", e)

    return _handle


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def stop_slack_bot() -> None:
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
    """Connect the Socket Mode bot. Returns True if started, False if tokens missing."""
    global _socket_client

    bot_token, app_token = _get_tokens(secrets)
    if not bot_token or not app_token:
        logger.info("[slack_bot] tokens not configured — bot disabled")
        return False

    _load_state()
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
            handler = _make_handler(bot_token)
            sc.socket_mode_request_listeners.append(handler)
            sc.connect()

            with _socket_lock:
                _socket_client = sc

            logger.info("[slack_bot] Socket Mode connected — bot ready (Block Kit enabled)")
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
