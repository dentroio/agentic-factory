"""Guards: SQLite connections use WAL, a busy timeout, and close (AF-26)."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_db():
    spec = importlib.util.spec_from_file_location("factory_db", ORCH / "db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_db"] = module
    spec.loader.exec_module(module)
    return module


def test_connect_enables_wal_and_closes(tmp_path):
    db = _load_db()
    path = tmp_path / "factory.db"
    with db.connect(path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert mode.lower() == "wal"
    assert int(timeout) == 30000
    with sqlite3.connect(path) as check:
        assert check.execute("SELECT id FROM t").fetchone() == (1,)


def test_connect_rolls_back_on_error(tmp_path):
    db = _load_db()
    path = tmp_path / "factory.db"
    with db.connect(path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO t VALUES (1)")
    try:
        with db.connect(path) as conn:
            conn.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with sqlite3.connect(path) as check:
        rows = [r[0] for r in check.execute("SELECT id FROM t").fetchall()]
    assert rows == [1]


def test_orchestrator_has_no_bare_sqlite_connect():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "sqlite3.connect(DB_PATH)" not in text
    assert "from db import connect as _db_connect" in text
    assert "def _db():" in text
    assert text.count("with _db() as") >= 30
