"""Per-WO persistent thread storage."""
import json
import time
from datetime import UTC, datetime
from pathlib import Path

THREADS_DIR = Path("/data/threads")
_counter = 0  # monotonic sub-millisecond tie-breaker


def _msg_id() -> str:
    global _counter
    _counter += 1
    return f"{int(time.time() * 1000):013d}{_counter:04d}"


def load_thread(wo_id: str) -> list[dict]:
    path = THREADS_DIR / f"{wo_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_thread(wo_id: str, messages: list[dict]) -> None:
    THREADS_DIR.mkdir(parents=True, exist_ok=True)
    (THREADS_DIR / f"{wo_id}.json").write_text(json.dumps(messages, indent=2))


def append_message(wo_id: str, msg: dict) -> dict:
    messages = load_thread(wo_id)
    messages.append(msg)
    save_thread(wo_id, messages)
    return msg


def make_message(
    author: str,
    role: str,
    msg_type: str,
    content: str,
    image_url: str = "",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": _msg_id(),
        "author": author,
        "role": role,
        "type": msg_type,
        "content": content,
        "image_url": image_url,
        "metadata": metadata or {},
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def system_message(content: str, metadata: dict | None = None) -> dict:
    return make_message("system", "system", "text", content, metadata=metadata)


def all_thread_summaries() -> dict[str, dict]:
    """Return {wo_id: {count, last_message}} for all persisted threads."""
    summaries = {}
    if not THREADS_DIR.exists():
        return summaries
    for path in THREADS_DIR.glob("*.json"):
        wo_id = path.stem
        try:
            msgs = json.loads(path.read_text())
            if msgs:
                summaries[wo_id] = {"count": len(msgs), "last": msgs[-1]}
        except Exception:
            pass
    return summaries
