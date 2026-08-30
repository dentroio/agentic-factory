# WO-1088 — Durable Orchestrator Run History & Audit Trail

**Created:** 2026-08-30
**Priority:** P2
**Effort:** M
**Services:** orchestrator, status-site, docs
**Depends on:** WO-1087
**Status:** 🟡 In Progress

---

## Background

The Orchestrator's SQLite `runs` table currently only stores in-flight active dispatch entries. When an agent finishes a work order (via `/api/complete`), when validation is rejected, or when an operator resets/releases a dispatch entry, the run is deleted or overwritten.

This leaves no durable record of:
- Historical run attempts and durations (cycle time)
- Failure classifications (e.g. lock timeout, node_modules, code error)
- Reviewer verdicts across runs
- Performance and throughput metrics by agent backend (Claude, Cursor, Codex)

This WO introduces a dedicated `run_history` table in SQLite, persists completed/failed/released runs, exposes REST endpoints (`/api/history`, `/api/history/metrics`, `/api/history/{wo_id}`), and adds an interactive History view to the Factory Status Dashboard.

## What to Build

1. **Database Layer (`services/orchestrator/db.py`)**:
   - `run_history` table schema & indices (`wo`, `slug`, `agent`, `backend`, `workstation`, `claimed_at`, `completed_at`, `duration_seconds`, `final_status`, `step`, `attempt_count`, `pr_number`, `pr_url`, `failure_category`, `failure_reason`, `review_verdicts`, `recorded_at`).
   - Helpers: `record_run_history`, `get_run_history`, `get_run_metrics`.

2. **Orchestrator Endpoints & Hooks (`services/orchestrator/orchestrator.py`)**:
   - Record run history on `/api/complete`, validation rejection, and release/clear.
   - `GET /api/history`: List runs with filtering (`wo`, `status`, `agent`, `limit`, `offset`).
   - `GET /api/history/metrics`: Aggregate metrics (runs, avg duration, pass rates by backend).
   - `GET /api/history/{wo_id}`: Single WO history trail.

3. **Factory Status Dashboard (`services/status-site/`)**:
   - Add `GET /history` view and navigation link.
   - Create `templates/history.html` with KPI metrics cards and filterable run table.

## Requirements

```yaml
requires:
  connectors: []
  services:
    - orchestrator
    - status-site
```

## Acceptance Criteria

- [ ] Completed WOs are persisted to `run_history` with duration, agent, backend, and PR details.
- [ ] `GET /api/history` returns historical runs with filtering and pagination.
- [ ] `GET /api/history/metrics` returns summary metrics across recorded runs.
- [ ] `/history` route on Factory Status renders metrics cards and run history table.
- [ ] `make ci-local` passes with full test coverage.

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `docs/work_orders/WO-1088-durable-orchestrator-history.md` | This spec |
| Modify | `services/orchestrator/db.py` | Run history schema, queries, metrics |
| Modify | `services/orchestrator/orchestrator.py` | Lifecycle recording hooks & API endpoints |
| Modify | `services/status-site/main.py` | History page and proxy routes |
| Create | `services/status-site/templates/history.html` | Dashboard history UI |
| Modify | `services/status-site/templates/base.html` | History nav link |
| Create | `tests/unit/test_run_history.py` | Unit tests for history DB and API |
| Modify | `docs/project_management/PROGRESS.md` | Track WO-1088 |
| Modify | `docs/project_management/CAPABILITY_STATUS.md` | Track WO-1088 capability |

## Execution

- **Branch:** `wo/1088-durable-orchestrator-history`
- **Risk tier:** P2 — auto-merge after CI
- **PR title:** `feat(orchestrator,status-site): WO-1088 — durable run history and audit trail`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1087
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md
