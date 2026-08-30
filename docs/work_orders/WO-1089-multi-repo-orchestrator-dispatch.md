# WO-1089 — Multi-Repo Autonomous Orchestrator Dispatch

**Created:** 2026-08-30
**Priority:** P2
**Effort:** M
**Services:** orchestrator, agent-runner, status-site, docs
**Depends on:** WO-1088
**Status:** 🟡 In Progress

---

## Background

Previously, the Factory Orchestrator only dispatched work orders for a single primary repository (`GITHUB_REPO`), ignoring secondary repositories registered in `/config/factory-config.json` or `SECONDARY_REPOS` during dispatch. Line 4194 in `orchestrator.py` explicitly skipped non-primary repository work orders from entering the dispatch queue.

This prevented the factory from autonomously managing and executing work orders across multiple projects simultaneously (e.g. `dentroio/agentic-factory`, `dentroio/clarion`, `dentroio/Oryntra`).

This WO enables multi-repo ingestion, polling, priority queue generation, repository-aware conflict isolation, and targeted dispatch.

## What to Build

1. **Database Schema (`services/orchestrator/db.py`)**:
   - Add `repo TEXT DEFAULT ''` column to `runs` and `run_history` tables with migration support.
   - Support `repo` in `record_run_history` and `get_run_history` filters.

2. **Project Ingestion & Polling (`services/orchestrator/orchestrator.py`)**:
   - Ingest all active configured projects dynamically from `factory-config.json` (falling back to `SECONDARY_REPOS` and `GITHUB_REPO`).
   - Poll active branches, open PRs, and work order specs across all configured repositories in parallel.
   - Tag all specs with their respective repository.

3. **Multi-Repo Dispatch & Queue (`services/orchestrator/orchestrator.py`)**:
   - Allow specs from all configured repositories into the priority queue and overlay.
   - Update `/api/next`:
     - Accept optional `repo` query parameter to allow runners to filter by project when desired.
     - Isolate file and service collision checks per repository (files with identical names in different repositories do not falsely block each other).
     - Return target `repo` and `wo_path` in `/api/next` dispatch payload.
   - Update `auto_mark_done_wo` and `complete_wo` to target the WO's actual repository.

4. **Status Site & Runner Compatibility**:
   - Expose `/api/factory/projects` returning all active configured projects.
   - Display repository context in history and dispatch views.

## Requirements

```yaml
requires:
  connectors: []
  services:
    - orchestrator
    - status-site
    - agent-runner
```

## Acceptance Criteria

- [ ] All configured projects in `factory-config.json` and `SECONDARY_REPOS` are polled for branches, PRs, and specs.
- [ ] `/api/next` selects candidate WOs across all configured repositories.
- [ ] `GET /api/next?repo=owner/repo` filters candidates strictly to the requested repository.
- [ ] File collision and occupancy checks are scoped per repository.
- [ ] SQLite `runs` and `run_history` persist the `repo` attribute.
- [ ] `make ci-local` passes with full test coverage.

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `docs/work_orders/WO-1089-multi-repo-orchestrator-dispatch.md` | This spec |
| Modify | `services/orchestrator/db.py` | Schema support for repo column in runs & history |
| Modify | `services/orchestrator/orchestrator.py` | Multi-repo polling, dispatch queue, and API |
| Create | `tests/unit/test_multi_repo_orchestration.py` | Multi-repo orchestration unit tests |
| Modify | `docs/project_management/PROGRESS.md` | Track WO-1089 |
| Modify | `docs/project_management/CAPABILITY_STATUS.md` | Track WO-1089 capability |

## Execution

- **Branch:** `wo/1089-multi-repo-orchestrator-dispatch`
- **Risk tier:** P2 — auto-merge after CI
- **PR title:** `feat(orchestrator): WO-1089 — multi-repo autonomous orchestrator dispatch`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1088
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md
