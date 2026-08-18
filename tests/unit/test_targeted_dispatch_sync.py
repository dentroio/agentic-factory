"""Guards: dispatch SQLite sync is targeted and does not swallow errors (AF-26)."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"

_RUNS_DDL = """
CREATE TABLE runs (
  wo TEXT PRIMARY KEY,
  slug TEXT DEFAULT '',
  agent TEXT DEFAULT '',
  backend TEXT DEFAULT '',
  workstation TEXT DEFAULT '',
  claimed_at TEXT,
  status TEXT DEFAULT 'claimed',
  step TEXT DEFAULT '',
  last_seen TEXT,
  completed_at TEXT,
  pr_url TEXT DEFAULT '',
  pr_number INTEGER,
  attempt_count INTEGER DEFAULT 0,
  first_claimed_at TEXT,
  retried_at TEXT,
  stuck INTEGER DEFAULT 0,
  stuck_since TEXT,
  claim_token TEXT DEFAULT ''
)
"""


def _load_db():
    spec = importlib.util.spec_from_file_location("factory_db_sync", ORCH / "db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_db_sync"] = module
    spec.loader.exec_module(module)
    return module


def _prepare(db, tmp_path):
    path = tmp_path / "factory.db"
    db.reset_writer_for_tests()
    with db.connect(path) as conn:
        conn.execute(_RUNS_DDL)
    return path


def test_sync_runs_skips_unchanged_rows(tmp_path):
    db = _load_db()
    path = _prepare(db, tmp_path)
    state = {
        "WO-1": {"status": "claimed", "agent": "a", "slug": "one"},
        "WO-2": {"status": "in_progress", "agent": "b", "slug": "two"},
    }
    assert db.sync_runs(path, state) == {"upserted": 2, "deleted": 0}
    assert db.sync_runs(path, state) == {"upserted": 0, "deleted": 0}
    state["WO-1"]["status"] = "complete"
    assert db.sync_runs(path, state) == {"upserted": 1, "deleted": 0}
    with sqlite3.connect(path) as conn:
        rows = {r[0]: r[1] for r in conn.execute("SELECT wo, status FROM runs")}
    assert rows == {"WO-1": "complete", "WO-2": "in_progress"}


def test_sync_runs_deletes_missing_rows(tmp_path):
    db = _load_db()
    path = _prepare(db, tmp_path)
    state = {"WO-1": {"status": "claimed"}, "WO-2": {"status": "claimed"}}
    db.sync_runs(path, state)
    del state["WO-1"]
    assert db.sync_runs(path, state) == {"upserted": 0, "deleted": 1}
    with sqlite3.connect(path) as conn:
        rows = [r[0] for r in conn.execute("SELECT wo FROM runs")]
    assert rows == ["WO-2"]


def test_sync_runs_raises_when_table_missing(tmp_path):
    db = _load_db()
    db.reset_writer_for_tests()
    path = tmp_path / "empty.db"
    with pytest.raises(sqlite3.OperationalError):
        db.sync_runs(path, {"WO-1": {"status": "claimed"}})
    # Cache must not mark the failed write as synced.
    with db.connect(path) as conn:
        conn.execute(_RUNS_DDL)
    assert db.sync_runs(path, {"WO-1": {"status": "claimed"}}) == {"upserted": 1, "deleted": 0}


def test_remember_runs_makes_first_save_a_noop(tmp_path):
    db = _load_db()
    path = _prepare(db, tmp_path)
    state = {"WO-1": {"status": "claimed", "agent": "a"}}
    db.sync_runs(path, state)
    db.remember_runs({})
    db.remember_runs(state)
    assert db.sync_runs(path, state) == {"upserted": 0, "deleted": 0}


def test_orchestrator_does_not_swallow_sync_failures():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "sync_dispatch failed" not in text
    assert "schedule_sync_runs as _db_schedule_sync_runs" in text
    assert "_db_schedule_sync_runs(DB_PATH, snapshot)" in text
    assert "_db_sync_runs(DB_PATH, snapshot)" in text
    assert "_db_remember_runs(_dispatch_state)" in text
    assert "asyncio.get_running_loop()" in text


def test_schedule_sync_runs_writes_off_the_caller_thread(tmp_path):
    db = _load_db()
    path = _prepare(db, tmp_path)
    state = {"WO-1": {"status": "claimed", "agent": "a", "slug": "one"}}
    db.schedule_sync_runs(path, state)
    state["WO-1"]["status"] = "mutated-after-schedule"
    db.flush_sync_runs()
    with sqlite3.connect(path) as conn:
        rows = {r[0]: r[1] for r in conn.execute("SELECT wo, status FROM runs")}
    assert rows == {"WO-1": "claimed"}


def test_schedule_sync_runs_surfaces_prior_failure(tmp_path):
    db = _load_db()
    db.reset_writer_for_tests()
    missing = tmp_path / "missing.db"
    db.schedule_sync_runs(missing, {"WO-1": {"status": "claimed"}})
    with pytest.raises(sqlite3.OperationalError):
        db.flush_sync_runs()
    path = _prepare(db, tmp_path)
    db.schedule_sync_runs(path, {"WO-1": {"status": "claimed"}})
    db.flush_sync_runs()
    with sqlite3.connect(path) as conn:
        rows = [r[0] for r in conn.execute("SELECT wo FROM runs")]
    assert rows == ["WO-1"]


def test_next_schedule_raises_prior_writer_failure(tmp_path):
    db = _load_db()
    db.reset_writer_for_tests()
    missing = tmp_path / "missing.db"
    db.schedule_sync_runs(missing, {"WO-1": {"status": "claimed"}})
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with db._writer_cv:
            failed = db._done_id >= 1 and db._error is not None
        if failed:
            break
        time.sleep(0.01)
    else:
        pytest.fail("writer did not record a failure")
    path = tmp_path / "ok.db"
    with db.connect(path) as conn:
        conn.execute(_RUNS_DDL)
    with pytest.raises(sqlite3.OperationalError):
        db.schedule_sync_runs(path, {"WO-1": {"status": "claimed"}})
    db.schedule_sync_runs(path, {"WO-1": {"status": "claimed"}})
    db.flush_sync_runs()
    with sqlite3.connect(path) as conn:
        rows = [r[0] for r in conn.execute("SELECT wo FROM runs")]
    assert rows == ["WO-1"]
