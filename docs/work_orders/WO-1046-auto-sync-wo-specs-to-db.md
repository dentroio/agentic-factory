# WO-1046 — Auto-Sync WO Specs to DB: Priority Normalization + Phase Inference

**Created:** 2026-07-23
**Priority:** P1
**Effort:** S
**Services:** orchestrator
**Depends on:** —
**Status:** Open

---

## Background

The orchestrator already auto-syncs new WO spec files into the SQLite queue on every poll cycle (`_plan_overlay` → `_db_upsert_queue_entry`). Three gaps remain that degrade the factory's accuracy:

1. **Dirty priority strings** — `_parse_priority()` returns the raw spec text: `"P2 (live UI contradiction visible today: ...)"`. The DB stores this verbatim. `plan_engine.next_wo()` sorts by priority string, so `"P1 (any authenticated viewer...)"` sorts after plain `"P1"`, silently reordering the queue.

2. **Phase not inferred** — new spec-file WOs land in the DB with `phase=""` (empty) when they have no PLAN.json entry. The status site shows them as "backlog" by default, but P1 WOs should default to `"now"`.

3. **Stale PLAN.json hides new WOs from the human-readable view** — PLAN.json is manually edited and can drift weeks behind. The DB is accurate but PLAN.json is what humans read in the repo.

Observed 2026-07-23: WO-1035–1038 (factory WOs) were seeded into the Clarion DB from an old PLAN.json, putting WO-1035 first in the queue ahead of all Clarion P1 work. Priority normalization + a startup guard would have surfaced this immediately.

## Acceptance Criteria

- [ ] `_parse_priority(content)` returns exactly `"P0"`, `"P1"`, `"P2"`, or `"P3"` — no parenthetical text
- [ ] When a new spec-file WO is inserted into the DB queue with no PLAN.json entry, its phase is inferred: P0/P1 → `"now"`, P2/P3 → `"backlog"`
- [ ] On startup, any DB queue entry whose WO spec file does not exist in the local repo mount is flagged with a log warning (guards against stale factory-WO seeds)
- [ ] After auto-sync, the orchestrator writes an updated `PLAN.json` back to the mounted repo — only appending WOs not already present, never overwriting human-set priority/phase/pin fields

## Implementation

### 1. Normalize `_parse_priority()`

```python
_PRIORITY_RE = re.compile(r"\bP([0-3])\b")

def _parse_priority(content: str) -> str:
    m = re.search(r"^\*\*Priority:\*\*\s*(.+)$", content, re.MULTILINE)
    if not m:
        return "P2"
    raw = m.group(1).strip()
    pm = _PRIORITY_RE.search(raw)
    return f"P{pm.group(1)}" if pm else "P2"
```

### 2. Infer phase in `_plan_overlay` loop

In `_db_upsert_queue_entry({**entry, "phase": spec.get("phase", "backlog")})`, replace the phase fallback:

```python
def _infer_phase(priority: str) -> str:
    return "now" if priority in ("P0", "P1") else "backlog"

# In the overlay loop:
_db_upsert_queue_entry({**entry, "phase": spec.get("phase") or _infer_phase(entry["priority"])})
```

### 3. Startup orphan check

After `_migrate_plan_json_to_db()`, scan the DB queue for WO IDs whose spec file does not exist in `LOCAL_REPO_MOUNT / WO_PATH`. Log a warning for each orphan (don't delete — the spec file may just not be mounted yet).

### 4. Write-back PLAN.json

After the overlay loop, if any new WOs were upserted, write them back to `PLAN.json` by appending to the `queue` array. Skip WOs already in PLAN.json. Only write fields that are safe to auto-populate: `wo`, `title`, `phase`, `priority`, `effort`, `depends_on`. Leave `pin`, `blocks_milestones`, `notes` at defaults.

## Files

- `services/orchestrator/orchestrator.py` — `_parse_priority()`, `_plan_overlay` loop, `_migrate_plan_json_to_db()` startup check, new `_writeback_plan_json()` helper
