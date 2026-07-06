"""Shared in-process state for quota-exhausted backends.

Both runner.py (writer) and draft_server.py (reader via /health) import this
module. Because they run in the same process, the set is shared in memory.
"""
_exhausted: set[str] = set()


def mark_exhausted(backend_name: str) -> None:
    _exhausted.add(backend_name)


def is_exhausted(backend_name: str) -> bool:
    return backend_name in _exhausted


def exhausted_backends() -> list[str]:
    return sorted(_exhausted)


def clear(backend_name: str | None = None) -> None:
    if backend_name:
        _exhausted.discard(backend_name)
    else:
        _exhausted.clear()
