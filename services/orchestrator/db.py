"""SQLite connection factory with WAL, busy timeout, and explicit close (AF-26)."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_RUN_KEYS = (
    "slug",
    "agent",
    "backend",
    "workstation",
    "claimed_at",
    "status",
    "step",
    "last_seen",
    "completed_at",
    "pr_url",
    "pr_number",
    "attempt_count",
    "first_claimed_at",
    "retried_at",
    "stuck",
    "stuck_since",
    "claim_token",
)

_UPSERT_SQL = """
INSERT INTO runs
  (wo, slug, agent, backend, workstation, claimed_at, status,
   step, last_seen, completed_at, pr_url, pr_number,
   attempt_count, first_claimed_at, retried_at, stuck, stuck_since,
   claim_token)
VALUES
  (:wo, :slug, :agent, :backend, :workstation, :claimed_at, :status,
   :step, :last_seen, :completed_at, :pr_url, :pr_number,
   :attempt_count, :first_claimed_at, :retried_at, :stuck, :stuck_since,
   :claim_token)
ON CONFLICT(wo) DO UPDATE SET
  slug=excluded.slug, agent=excluded.agent, backend=excluded.backend,
  workstation=excluded.workstation, claimed_at=excluded.claimed_at,
  status=excluded.status, step=excluded.step,
  last_seen=excluded.last_seen, completed_at=excluded.completed_at,
  pr_url=excluded.pr_url, pr_number=excluded.pr_number,
  attempt_count=excluded.attempt_count, first_claimed_at=excluded.first_claimed_at,
  retried_at=excluded.retried_at, stuck=excluded.stuck, stuck_since=excluded.stuck_since,
  claim_token=excluded.claim_token
"""

_synced: dict[str, tuple] = {}
_synced_lock = threading.Lock()

_writer_cv = threading.Condition()
_pending: tuple[str, dict[str, dict], int] | None = None
_job_id = 0
_done_id = 0
_error: BaseException | None = None
_writer_thread: threading.Thread | None = None


@contextmanager
def connect(path: Path | str, timeout: float = 30.0) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path), timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row(wo_id: str, record: dict) -> dict:
    return {
        "wo": wo_id,
        "slug": record.get("slug", ""),
        "agent": record.get("agent", ""),
        "backend": record.get("backend", ""),
        "workstation": record.get("workstation", ""),
        "claimed_at": record.get("claimed_at"),
        "status": record.get("status", "claimed"),
        "step": record.get("step", ""),
        "last_seen": record.get("last_seen"),
        "completed_at": record.get("completed_at"),
        "pr_url": record.get("pr_url", ""),
        "pr_number": record.get("pr_number"),
        "attempt_count": record.get("attempt_count", 0),
        "first_claimed_at": record.get("first_claimed_at"),
        "retried_at": record.get("retried_at"),
        "stuck": int(bool(record.get("stuck", False))),
        "stuck_since": record.get("stuck_since"),
        "claim_token": record.get("claim_token") or "",
    }


def _fingerprint(wo_id: str, record: dict) -> tuple:
    row = _row(wo_id, record)
    return tuple(row[k] for k in ("wo",) + _RUN_KEYS)


def remember_runs(records: dict[str, dict]) -> None:
    """Seed the fingerprint cache after a SQLite load so the next save is a no-op."""
    with _synced_lock:
        _synced.clear()
        for wo_id, record in records.items():
            _synced[wo_id] = _fingerprint(wo_id, record)


def sync_runs(path: Path | str, records: dict[str, dict]) -> dict[str, int]:
    """Upsert changed runs and delete missing ones. Raises on SQLite errors."""
    with _synced_lock:
        current = {wo_id: _fingerprint(wo_id, rec) for wo_id, rec in records.items()}
        to_delete = [wo_id for wo_id in _synced if wo_id not in current]
        to_upsert = [wo_id for wo_id, fp in current.items() if _synced.get(wo_id) != fp]
        if not to_delete and not to_upsert:
            return {"upserted": 0, "deleted": 0}
        with connect(path) as conn:
            for wo_id in to_delete:
                conn.execute("DELETE FROM runs WHERE wo = ?", (wo_id,))
            for wo_id in to_upsert:
                conn.execute(_UPSERT_SQL, _row(wo_id, records[wo_id]))
        for wo_id in to_delete:
            _synced.pop(wo_id, None)
        for wo_id in to_upsert:
            _synced[wo_id] = current[wo_id]
        return {"upserted": len(to_upsert), "deleted": len(to_delete)}


def _snapshot_records(records: dict[str, dict]) -> dict[str, dict]:
    return {
        wo_id: dict(record) if isinstance(record, dict) else record
        for wo_id, record in records.items()
    }


def _raise_pending_error() -> None:
    global _error
    if _error is not None:
        err, _error = _error, None
        raise err


def _ensure_writer() -> None:
    global _writer_thread
    if _writer_thread is None or not _writer_thread.is_alive():
        _writer_thread = threading.Thread(
            target=_writer_loop, name="factory-runs-writer", daemon=True
        )
        _writer_thread.start()


def _writer_loop() -> None:
    global _pending, _done_id, _error
    while True:
        with _writer_cv:
            while _pending is None:
                _writer_cv.wait()
            path, records, job_id = _pending
            _pending = None
        try:
            sync_runs(path, records)
            err: BaseException | None = None
        except BaseException as e:
            err = e
        with _writer_cv:
            _error = err
            _done_id = job_id
            _writer_cv.notify_all()


def schedule_sync_runs(path: Path | str, records: dict[str, dict]) -> None:
    """Copy records and persist them on a background thread.

    Raises a prior writer failure so SQLite errors are not swallowed. The
    in-memory dict stays the source of truth; this is write-behind.
    """
    global _pending, _job_id
    snapshot = _snapshot_records(records)
    with _writer_cv:
        _raise_pending_error()
        _job_id += 1
        _pending = (str(path), snapshot, _job_id)
        _ensure_writer()
        _writer_cv.notify()


def flush_sync_runs(timeout: float = 5.0) -> None:
    """Wait until every scheduled snapshot has been written. Raises on failure."""
    with _writer_cv:
        target = _job_id
        if not _writer_cv.wait_for(lambda: _done_id >= target, timeout=timeout):
            raise TimeoutError("sqlite runs writer did not flush")
        _raise_pending_error()


def reset_writer_for_tests() -> None:
    """Drop queued work and fingerprint cache. The daemon thread is reused."""
    global _pending, _job_id, _done_id, _error
    with _writer_cv:
        _pending = None
        _job_id = 0
        _done_id = 0
        _error = None
    remember_runs({})
