"""Per-WO persistent thread storage."""
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import dispatch_control

THREADS_DIR = Path("/data/threads")
_counter = 0  # monotonic sub-millisecond tie-breaker

_WO_ID = re.compile(r"^WO-\d+$", re.IGNORECASE)
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class UnsafePath(ValueError):
    """A WO id or filename is not a single safe path segment."""


def require_wo_id(wo: str) -> str:
    wo = (wo or "").strip()
    if not _WO_ID.fullmatch(wo):
        raise UnsafePath("invalid wo id")
    return f"WO-{wo.split('-', 1)[1]}"


def require_image_filename(name: str) -> str:
    name = (name or "").strip()
    if name in {".", ".."} or not _IMAGE_NAME.fullmatch(name):
        raise UnsafePath("invalid filename")
    return name


def contained_path(root: Path, *parts: str) -> Path:
    """Join parts under root; raise if any segment is unsafe or the result escapes (AF-28)."""
    for part in parts:
        if not part or part in {".", ".."} or "/" in part or "\\" in part or "\x00" in part:
            raise UnsafePath("invalid path segment")
    root = Path(root).resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise UnsafePath("path escapes root")
    return path


def _msg_id() -> str:
    global _counter
    _counter += 1
    return f"{int(time.time() * 1000):013d}{_counter:04d}"


def load_thread(wo_id: str) -> list[dict]:
    wo_id = require_wo_id(wo_id)
    path = contained_path(THREADS_DIR, f"{wo_id}.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_thread(wo_id: str, messages: list[dict]) -> None:
    wo_id = require_wo_id(wo_id)
    THREADS_DIR.mkdir(parents=True, exist_ok=True)
    dispatch_control.atomic_write_json(contained_path(THREADS_DIR, f"{wo_id}.json"), messages)


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
