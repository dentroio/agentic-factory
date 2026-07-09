# WO-1021 — SQLite Queue Migration: Move PLAN.json Queue to Database

**Created:** 2026-07-09
**Priority:** P1
**Effort:** M
**Status:** ✅ Complete
**Services:** orchestrator, status-site
**Depends on:** —
**Blocks:** WO-1022, WO-1023

---

## Background

`PLAN.json` in the target repo serves two roles: a priority queue (which WOs to run next, in what order) and a planning definition file (phases, milestones). The queue role is fundamentally operational state — it changes every time a WO ships, a priority changes, or the PM reorders work. Storing it as a git-tracked file creates drift: WOs that complete never get removed from the queue because nothing writes back to the file automatically. The result is PLAN.json accumulating stale done entries (we recently found 30 completed WOs still in the queue).

The fix is to move the queue, phases, and milestones into the orchestrator's existing SQLite database (`/data/factory.db`), where the orchestrator can keep it current automatically and the UI can edit it without file I/O. WO status continues to come from spec files — that doesn't change.

---

## What to Build

### 1. Add three tables to `factory.db`

In `_init_db()` in `orchestrator.py`:

```sql
CREATE TABLE IF NOT EXISTS queue (
    wo          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    phase       TEXT,
    priority    TEXT NOT NULL DEFAULT 'P2',
    effort      TEXT,
    position    INTEGER NOT NULL DEFAULT 9999,
    pin         INTEGER NOT NULL DEFAULT 0,
    blocks_milestones TEXT DEFAULT '[]',   -- JSON array
    depends_on  TEXT DEFAULT '[]',          -- JSON array
    notes       TEXT DEFAULT '',
    added_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS phases (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    target_date TEXT,
    milestone_id TEXT,
    parallel    INTEGER NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 9999
);

CREATE TABLE IF NOT EXISTS milestones (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    target_date TEXT,
    description TEXT DEFAULT ''
);
```

### 2. One-time migration on startup

On first boot after this WO ships, if `factory.db` has empty queue/phases/milestones tables but `PLAN_PATH` exists on the filesystem, import PLAN.json into the DB. After import, write a sentinel file (`.plan_migrated`) next to PLAN.json so the import never runs twice.

```python
def _migrate_plan_json_to_db(conn):
    """Import PLAN.json into SQLite on first boot. Idempotent."""
    sentinel = Path(PLAN_PATH).parent / ".plan_migrated"
    if sentinel.exists():
        return
    plan_path = Path(LOCAL_REPO_MOUNT) / PLAN_PATH if LOCAL_REPO_MOUNT else Path(PLAN_PATH)
    if not plan_path.exists():
        return
    plan = json.loads(plan_path.read_text())
    for i, w in enumerate(plan.get("queue", [])):
        conn.execute("INSERT OR IGNORE INTO queue (...) VALUES (...)", ...)
    for p in plan.get("phases", []):
        conn.execute("INSERT OR IGNORE INTO phases (...) VALUES (...)", ...)
    for m in plan.get("milestones", []):
        conn.execute("INSERT OR IGNORE INTO milestones (...) VALUES (...)", ...)
    conn.commit()
    sentinel.touch()
```

### 3. Replace all PLAN.json reads with DB reads

Replace `plan_raw = json.loads(...)` and all PLAN.json file reads in the orchestrator's poll loop and `/api/next` with queries to the `queue`, `phases`, and `milestones` tables.

### 4. Auto-cleanup: remove done WOs from queue each poll cycle

At the end of each `_poll()` cycle, after spec files are scanned:

```python
done_wos = {f"WO-{n}" for n, spec in specs.items() if _is_done(spec.get("status", ""))}
with sqlite3.connect(DB_PATH) as conn:
    for wo in done_wos:
        conn.execute("DELETE FROM queue WHERE wo = ?", (wo,))
    conn.commit()
```

This makes the queue self-healing. WOs that complete in their spec files are automatically removed from the queue on the next poll cycle.

### 5. New CRUD endpoints

```
GET  /api/queue                  → list all queue entries ordered by position
POST /api/queue                  → add a WO to the queue
DELETE /api/queue/{wo}           → remove a WO from the queue
PUT  /api/queue/{wo}/position    → reorder (accepts {position: N} or {before: "WO-NNN"})
PUT  /api/queue/{wo}             → update priority, effort, phase, notes, pin, blocks_milestones
GET  /api/phases                 → list phases
POST /api/phases                 → create phase
PUT  /api/phases/{id}            → update phase
DELETE /api/phases/{id}          → delete phase
GET  /api/milestones             → list milestones
POST /api/milestones             → create milestone
PUT  /api/milestones/{id}        → update milestone
DELETE /api/milestones/{id}      → delete milestone
```

### 6. Wire the Plan Authoring UI to the new endpoints

Update `github_writer.py`: `add_phase()` and `add_milestone()` now call the new DB endpoints instead of writing to PLAN.json. The `create_wo()` function's PLAN.json insertion step calls `POST /api/queue` instead.

Update the status-site Plan Authoring routes to call the new endpoints.

### 7. Remove PLAN.json write paths

Once the DB is the source of truth, remove all code that writes to PLAN.json. The file can remain in the repo as a read-only reference snapshot for humans — it just won't be written by the orchestrator anymore.

---

## Acceptance Criteria

- [ ] `factory.db` has `queue`, `phases`, and `milestones` tables after upgrade
- [ ] PLAN.json is imported on first boot; import does not run twice
- [ ] `/api/next` returns the correct next WO using DB queue order
- [ ] Completing a WO (spec file → ✅) removes it from the DB queue within one poll cycle
- [ ] `POST /api/queue` adds a WO; `DELETE /api/queue/{wo}` removes it
- [ ] Creating a WO via the Plan Authoring UI adds it to the DB queue without touching PLAN.json
- [ ] Adding phases and milestones via the UI writes to the DB
- [ ] The `/plan` board view renders correctly using DB-sourced queue, phases, milestones
- [ ] `make smoke-test` passes after rebuild

## Documentation Required

- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — replace PLAN.json description with DB schema; update orchestrator endpoints table with new CRUD endpoints
- [ ] Update `docs/ENGINEER_OVERVIEW.md` if it references PLAN.json as the queue store
