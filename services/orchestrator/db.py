"""SQLite connection factory with WAL, busy timeout, and explicit close (AF-26)."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
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


# ── Run History & Audit Trail ──────────────────────────────────────────────────

_CREATE_HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wo TEXT NOT NULL,
    slug TEXT DEFAULT '',
    agent TEXT DEFAULT '',
    backend TEXT DEFAULT '',
    workstation TEXT DEFAULT '',
    claimed_at TEXT,
    completed_at TEXT,
    duration_seconds INTEGER DEFAULT 0,
    final_status TEXT NOT NULL,
    step TEXT DEFAULT '',
    attempt_count INTEGER DEFAULT 1,
    pr_number INTEGER,
    pr_url TEXT DEFAULT '',
    failure_category TEXT DEFAULT '',
    failure_reason TEXT DEFAULT '',
    review_verdicts TEXT DEFAULT '{}',
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_HISTORY_INDICES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_run_history_wo ON run_history(wo);",
    "CREATE INDEX IF NOT EXISTS idx_run_history_recorded_at ON run_history(recorded_at);",
    "CREATE INDEX IF NOT EXISTS idx_run_history_final_status ON run_history(final_status);",
]


def init_history_table(path: Path | str) -> None:
    """Ensure run_history table and its indices exist."""
    with connect(path) as conn:
        conn.execute(_CREATE_HISTORY_TABLE_SQL)
        for idx_sql in _CREATE_HISTORY_INDICES_SQL:
            conn.execute(idx_sql)


def _compute_duration_seconds(claimed_at: str | None, completed_at: str | None) -> int:
    if not claimed_at or not completed_at:
        return 0
    try:
        c_dt = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
        f_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return max(0, int((f_dt - c_dt).total_seconds()))
    except Exception:
        return 0


def record_run_history(path: Path | str, record: dict) -> int:
    """Persist a completed, failed, or released run to the durable audit trail."""
    init_history_table(path)
    wo = str(record.get("wo") or "")
    if not wo:
        return 0

    claimed_at = record.get("first_claimed_at") or record.get("claimed_at")
    completed_at = record.get("completed_at") or datetime.now(UTC).isoformat()
    duration_seconds = record.get("duration_seconds")
    if duration_seconds is None:
        duration_seconds = _compute_duration_seconds(claimed_at, completed_at)

    review_verdicts = record.get("review_verdicts", {})
    if isinstance(review_verdicts, dict):
        review_verdicts_str = json.dumps(review_verdicts)
    else:
        review_verdicts_str = str(review_verdicts or "{}")

    row = {
        "wo": wo,
        "slug": str(record.get("slug") or ""),
        "agent": str(record.get("agent") or ""),
        "backend": str(record.get("backend") or ""),
        "workstation": str(record.get("workstation") or ""),
        "claimed_at": claimed_at,
        "completed_at": completed_at,
        "duration_seconds": int(duration_seconds),
        "final_status": str(record.get("final_status") or record.get("status") or "complete"),
        "step": str(record.get("step") or ""),
        "attempt_count": int(record.get("attempt_count") or 1),
        "pr_number": record.get("pr_number"),
        "pr_url": str(record.get("pr_url") or ""),
        "failure_category": str(record.get("failure_category") or ""),
        "failure_reason": str(record.get("failure_reason") or ""),
        "review_verdicts": review_verdicts_str,
        "recorded_at": datetime.now(UTC).isoformat(),
    }

    insert_sql = """
    INSERT INTO run_history (
        wo, slug, agent, backend, workstation, claimed_at, completed_at,
        duration_seconds, final_status, step, attempt_count, pr_number,
        pr_url, failure_category, failure_reason, review_verdicts, recorded_at
    ) VALUES (
        :wo, :slug, :agent, :backend, :workstation, :claimed_at, :completed_at,
        :duration_seconds, :final_status, :step, :attempt_count, :pr_number,
        :pr_url, :failure_category, :failure_reason, :review_verdicts, :recorded_at
    )
    """
    with connect(path) as conn:
        cursor = conn.execute(insert_sql, row)
        return int(cursor.lastrowid or 0)


def get_run_history(
    path: Path | str,
    wo: str | None = None,
    status: str | None = None,
    agent: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Query run history records with optional filtering."""
    init_history_table(path)
    clauses = ["1=1"]
    params: list = []

    if wo:
        clauses.append("wo = ?")
        params.append(wo)
    if status:
        clauses.append("final_status = ?")
        params.append(status)
    if agent:
        clauses.append("agent = ?")
        params.append(agent)

    where_str = " AND ".join(clauses)
    query_sql = f"""
    SELECT * FROM run_history
    WHERE {where_str}
    ORDER BY id DESC
    LIMIT ? OFFSET ?
    """
    params.extend([max(1, min(500, limit)), max(0, offset)])

    with connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query_sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["review_verdicts"] = json.loads(d.get("review_verdicts") or "{}")
            except Exception:
                d["review_verdicts"] = {}
            results.append(d)
        return results


def get_run_metrics(path: Path | str) -> dict:
    """Calculate aggregate performance and reliability metrics from run history."""
    init_history_table(path)
    with connect(path) as conn:
        conn.row_factory = sqlite3.Row
        
        # Overall counts
        total = conn.execute("SELECT COUNT(*) as cnt FROM run_history").fetchone()["cnt"]
        completed = conn.execute("SELECT COUNT(*) as cnt FROM run_history WHERE final_status = 'complete'").fetchone()["cnt"]
        failed = conn.execute("SELECT COUNT(*) as cnt FROM run_history WHERE final_status = 'failed'").fetchone()["cnt"]
        released = conn.execute("SELECT COUNT(*) as cnt FROM run_history WHERE final_status = 'released'").fetchone()["cnt"]
        
        # Duration averages (for completed runs with positive duration)
        avg_dur_row = conn.execute(
            "SELECT AVG(duration_seconds) as avg_dur FROM run_history WHERE final_status = 'complete' AND duration_seconds > 0"
        ).fetchone()
        avg_duration = round(float(avg_dur_row["avg_dur"] or 0.0), 1)

        # By backend
        backend_rows = conn.execute("""
            SELECT 
                backend, 
                COUNT(*) as total,
                SUM(CASE WHEN final_status = 'complete' THEN 1 ELSE 0 END) as completed,
                AVG(CASE WHEN final_status = 'complete' AND duration_seconds > 0 THEN duration_seconds ELSE NULL END) as avg_dur
            FROM run_history
            WHERE backend != ''
            GROUP BY backend
        """).fetchall()

        by_backend = {}
        for r in backend_rows:
            by_backend[r["backend"]] = {
                "total": r["total"],
                "completed": r["completed"],
                "avg_duration_seconds": round(float(r["avg_dur"] or 0.0), 1) if r["avg_dur"] is not None else 0.0,
            }

        # By failure category
        fail_rows = conn.execute("""
            SELECT failure_category, COUNT(*) as cnt
            FROM run_history
            WHERE failure_category != ''
            GROUP BY failure_category
            ORDER BY cnt DESC
        """).fetchall()
        by_failure_category = {r["failure_category"]: r["cnt"] for r in fail_rows}

        pass_rate = round((completed / total * 100.0), 1) if total > 0 else 100.0

        return {
            "total_runs": total,
            "completed_runs": completed,
            "failed_runs": failed,
            "released_runs": released,
            "pass_rate_pct": pass_rate,
            "avg_duration_seconds": avg_duration,
            "by_backend": by_backend,
            "by_failure_category": by_failure_category,
        }
