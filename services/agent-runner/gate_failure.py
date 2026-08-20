"""Classify quality-gate CI output so close-out can retry infra vs fix code.

Park-on-fail made failures visible but parked lock timeouts, missing
node_modules, and 30-minute frontend-check hangs the same way as a one-line
pytest miss. The agent cannot edit its way out of the first three.
"""
from __future__ import annotations

import re

LOCK = "lock_timeout"
NODE_MODULES = "node_modules"
TIMEOUT = "timeout"
CODE = "code"
UNKNOWN = "unknown"

_LOCK_MARKERS = (
    "ci lock wait timed out",
    "another ci run held the lock",
)
_NODE_MARKERS = (
    "failed to resolve entry for package",
    "cannot find module",
    "lucide-react",
    "enoent",
    "error ts2307",
)
_TIMEOUT_RE = re.compile(r"timed out after \d+s", re.I)
_CODE_MARKERS = (
    "failed tests/",
    "assertionerror",
    "e   assert",
    "error during build",
    "make[1]: *** [test]",
    "make[1]: *** [lint]",
)


def classify_ci_output(output: str) -> str:
    """Return one of lock_timeout, node_modules, timeout, code, unknown."""
    text = (output or "").lower()
    if not text.strip():
        return UNKNOWN
    if any(m in text for m in _LOCK_MARKERS):
        return LOCK
    if any(m in text for m in _NODE_MARKERS) and "failed tests/" not in text:
        return NODE_MODULES
    # A real pytest failure beats a later wall-clock timeout wrapping the log.
    if any(m in text for m in _CODE_MARKERS):
        return CODE
    if _TIMEOUT_RE.search(text) or "make timed out after" in text:
        return TIMEOUT
    return UNKNOWN


def is_infra(kind: str) -> bool:
    return kind in {LOCK, NODE_MODULES, TIMEOUT}


def error_excerpt(output: str, limit: int = 8) -> str:
    raw = output or ""
    keys = ("error", "failed", "assert", "exception", "traceback", "import", "syntax", "timed out")
    lines = [
        line.rstrip()
        for line in raw.splitlines()
        if line.strip() and any(w in line.lower() for w in keys)
    ]
    if lines:
        return "\n".join(lines[:limit])
    return raw[-400:].strip()


def park_reason(kind: str, failure_str: str) -> str:
    return f"quality gate failed ({kind}): {failure_str}"
