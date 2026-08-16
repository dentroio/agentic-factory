---
name: orchestrator-sqlite-must-use-db-connect-helper
description: All factory.db access in orchestrator.py must go through db.py's connect() helper, not raw sqlite3.connect()
metadata:
  type: project
---

`services/orchestrator/orchestrator.py` must never call `sqlite3.connect(DB_PATH)` directly. Use the local `_db()` helper (wraps `db.connect()` from `services/orchestrator/db.py`), which enables WAL mode, sets a 30s busy_timeout, commits/rolls back automatically, and always closes the connection.

**Why:** Bare `sqlite3.connect()` calls previously left connections without WAL/busy_timeout and could leak handles or leave the DB in `DELETE` journal mode, causing lock contention under concurrent orchestrator + API access. A regression test (`tests/unit/test_sqlite_wal.py