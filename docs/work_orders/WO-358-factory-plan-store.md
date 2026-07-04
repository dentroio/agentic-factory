# WO-358 — Factory Plan Store + Priority Queue

**Status:** ✅ Complete
**Priority:** P1
**Repo:** `dentroio/agentic-factory`
**Service:** `services/status-site/` + `services/orchestrator/`
**Estimated effort:** 2–3 days
**Depends on:** WO-356 (orchestrator loop)
**Design:** See `docs/factory/PLAN.json` (schema defined by this WO)

---

## Why

The factory currently surfaces WO status but has no concept of *order*. Agents are told what WO to work on via a human prompt. The orchestrator produces an advisory but derives priority from WO markdown fields alone — it has no awareness of milestones, phases, or business urgency.

This WO adds the **plan layer**: a human-maintained, machine-consumed priority queue that the factory serves as an API. Agents and the orchestrator pull from it instead of being told. The human controls what matters and when; the factory handles the rest.

---

## Deliverables

### 1. `docs/factory/PLAN.json` — Authoritative plan store (clarion repo)

Schema defined below. Lives at `docs/factory/PLAN.json` in `dentroio/clarion`. The factory-status service reads this file from GitHub on each poll cycle (same pattern as WO files). The orchestrator reads it too.

**Schema:**

```json
{
  "schema_version": "1.0",
  "last_updated": "YYYY-MM-DD",
  "repository": "dentroio/clarion",
  "milestones": [
    {
      "id": "string",
      "label": "string",
      "target_date": "YYYY-MM-DD",
      "description": "string"
    }
  ],
  "phases": [
    {
      "id": "string",
      "label": "string",
      "target_date": "YYYY-MM-DD",
      "milestone": "milestone-id | null",
      "description": "string",
      "parallel": false
    }
  ],
  "queue": [
    {
      "wo": "WO-NNN",
      "title": "string",
      "phase": "phase-id",
      "priority": "P1 | P2 | P3",
      "effort": "S | M | L",
      "blocks_milestones": ["milestone-id"],
      "depends_on": ["WO-NNN"],
      "status": "open | claimed | in_progress | review | done | deferred",
      "pin": false,
      "notes": "optional string"
    }
  ]
}
```

**Status lifecycle:**
`open` → `claimed` → `in_progress` → `review` → `done`

Status is **not** hand-edited — it is synced from WO markdown files + claim files + PR state by the orchestrator on each poll cycle. Human edits only `priority`, `phase`, `effort`, `blocks_milestones`, `depends_on`, `pin`, and whether a WO is `deferred`.

### 2. Priority engine — `services/orchestrator/plan_engine.py` (new file)

Pure function: given `PLAN.json` + current WO statuses, return the ordered dispatch queue.

```python
def next_wo(plan: dict, wo_statuses: dict[str, str]) -> dict | None:
    """Return highest-priority unclaimed, unblocked WO entry, or None."""
```

**Sort algorithm:**
1. Exclude `done`, `deferred`, `claimed`, `in_progress`, `review`
2. Exclude any WO where any `depends_on` entry is not `done`
3. Among remaining, sort by:
   a. `pin == true` first
   b. Phase order (phase list index, ascending) — but `parallel` phases interleave at P1
   c. Within phase: P1 → P2 → P3
   d. Within priority: effort S → M → L (maximise throughput)
   e. Within effort: WOs blocking more milestones first (len `blocks_milestones` desc)
4. Return first entry

### 3. Orchestrator sync — `services/orchestrator/orchestrator.py` (update)

Add `plan_engine` import. On each poll cycle:
- Fetch `docs/factory/PLAN.json` from GitHub (same pattern as WO files)
- For each queue entry, sync `status` from WO markdown + claim file + open PR state
- Write updated plan state into `orchestrator.json` under a `"plan"` key
- Expose `next_wo` result as `orchestrator.json["plan"]["next"]`

### 4. factory-status API — `services/status-site/main.py` (update)

Add three endpoints:

```
GET  /api/plan          — full plan + milestone health computed from orchestrator.json
GET  /api/plan/next     — single WO entry: the next unclaimed, unblocked WO
PATCH /api/plan/wos/{wo} — update priority/phase/effort/pin/deferred (writes back to PLAN.json via GitHub API)
```

`/api/plan` response shape:
```json
{
  "milestones": [
    {
      "id": "beta",
      "label": "v1.0-beta",
      "target_date": "2026-08-15",
      "on_track": true,
      "days_remaining": 44,
      "open_blockers": ["WO-343", "WO-337"],
      "done_count": 3,
      "total_count": 7
    }
  ],
  "phases": [...],
  "queue": [...],
  "next": { ...single WO entry... },
  "generated_at": "ISO-8601"
}
```

`/api/plan/next` response: the single highest-priority WO entry, or `{"wo": null}` if nothing is ready.

### 5. Plan tab — `services/status-site/templates/` (update)

New tab "Plan" in the factory dashboard navigation. Layout:

```
┌─────────────────────────────────────────────────────────────┐
│  MILESTONES                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ v1.0-beta        │  │ Investor-ready   │                 │
│  │ Aug 15 · 44d     │  │ Sep 15 · 74d     │                 │
│  │ ⚠️  ON TRACK      │  │ ⚠️  AT RISK       │                 │
│  │ 3/7 blockers done│  │ 0/8 blockers done│                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                              │
│  PHASE 1 — Beta Blockers          Jul 18    ████░░░░  3/6   │
│  PHASE 2 — Beta Completion        Aug 8     ░░░░░░░░  0/4   │
│  PHASE 3 — Investor-Ready         Sep 12    ░░░░░░░░  0/8   │
│  FACTORY SDLC (parallel)          Jul 15    ░░░░░░░░  0/3   │
│                                                              │
│  PRIORITY QUEUE                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ → WO-343  UI Documentation Audit          P2  S  open │  │
│  │   WO-337  Operate Nav Alignment           P2  S  open │  │
│  │   WO-358  Factory Plan Store              P1  M  open │  │ ← this WO
│  │   WO-338  Settings Nav Alignment          P2  S  open │  │
│  │   WO-344  Investor Docs                   P1  M  open │  │
│  │   ...                                                  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

The `→` arrow marks the current `/api/plan/next` WO. Status chips use colour coding: `open` (grey), `claimed` (blue), `in_progress` (amber), `review` (purple), `done` (green), `deferred` (slate).

---

## AGENT_PROCESS.md update

Add to §Step 0 (before `make wo-start`):

```
# Check what to work on next (replaces human-assigned WO prompt)
NEXT=$(curl -s http://localhost:8099/api/plan/next)
echo $NEXT | jq .
# Proceed with the WO returned, or use the WO assigned in your prompt
```

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `docs/factory/PLAN.json` exists in clarion repo with correct schema; initial queue seeded |
| 2 | `GET /api/plan/next` returns highest-priority open, unblocked WO |
| 3 | Orchestrator syncs WO status into PLAN on each cycle; `orchestrator.json` has `plan.next` |
| 4 | Plan tab renders in factory dashboard with milestone cards + phase bars + queue list |
| 5 | `PATCH /api/plan/wos/{wo}` writes priority/phase/pin changes back to PLAN.json via GitHub API |
| 6 | Agent can curl `/api/plan/next` and get a valid WO to start |

---

## Files to Create / Modify

| File | Action | Repo |
|------|--------|------|
| `docs/factory/PLAN.json` | **Create** — initial queue from July 2026 audit | clarion |
| `services/orchestrator/plan_engine.py` | **Create** — priority sort algorithm | agentic-factory |
| `services/orchestrator/orchestrator.py` | **Modify** — fetch PLAN.json, sync statuses, write `plan.next` | agentic-factory |
| `services/status-site/main.py` | **Modify** — add `/api/plan`, `/api/plan/next`, `PATCH` endpoints | agentic-factory |
| `services/status-site/templates/` | **Modify** — add Plan tab | agentic-factory |
| `AGENT_PROCESS.md` | **Modify** — add plan/next check to Step 0 | clarion |
| `docs/project_management/PROGRESS.md` | **Modify** — Factory SDLC program section | clarion |
