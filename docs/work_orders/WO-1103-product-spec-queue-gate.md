# WO-1103 — Refuse non-product WOs on the Clarion factory queue

**Created:** 2026-09-13
**Priority:** P2
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** —
**Status:** ✅ Complete (2026-09-13)

---

## Problem

This factory instance is pointed at Clarion (`GITHUB_REPO=dentroio/clarion`), but the
orchestrator queue is a flat list with **no repo column**. Engine Work Orders
(`dentroio/agentic-factory` specs under `docs/work_orders/`, e.g. WO-1048–1051,
WO-1095–1096) can be POSTed into the queue (PM Create WO, Oryntra, leftovers) and
runners will claim them against the Clarion worktree.

Found live 2026-09-13: engine WOs appeared as Open/Running/Stalled on the Clarion
board and Cursor/Claude re-claimed already-shipped engine work (WO-1096).

## What to Build

1. Helper: a WO is **product-eligible** only if a spec file exists under the
   product mount `LOCAL_REPO_MOUNT / WO_PATH` (`WO-{n}-*.md`), or the primary
   `_specs_cache` entry for that number belongs to `GITHUB_REPO`.
2. **`POST /api/queue`** — reject (400) non-product-eligible WOs.
3. **`POST /api/claim`** — reject (404) non-product-eligible WOs.
4. **`GET /api/next`** — skip non-product-eligible queue rows (do not offer them).
5. On each poll (or startup orphan check): **auto-delete** queue rows with no
   product spec (log the purge).
6. Unit tests for the eligibility helper + gate behavior.

## Out of scope

- Multi-repo queue rows with a real `repo` column (future)
- Changing Oryntra export UX
- Board overlay display of engine specs (WO-1100)

## Do NOT change

- Spec path defaults (`docs/project_management/work_orders`)
- Ability to manually `DELETE /api/queue/{wo}`

## Acceptance Criteria

- [ ] `POST /api/queue` with a WO that has no Clarion product spec returns 400
- [ ] `POST /api/claim` for that WO returns 404
- [ ] `GET /api/next` never returns a WO lacking a product spec
- [ ] Orphan queue rows without product specs are removed on poll/startup
- [ ] A normal Clarion WO with a mount/spec file still enqueues and claims
- [ ] `make ci-local` passes

## Execution

- **Branch:** `wo/1103-product-spec-queue-gate`
- **Risk tier:** P2 — auto-merge after verify (API curl; no Clarion UI required)
- **PR title:** `fix(orchestrator): WO-1103 — refuse non-product WOs on the queue`
- **PM docs:** PROGRESS.md, BACKLOG.md, CAPABILITY_STATUS.md
- **Do not** add this WO to the Clarion orchestrator queue

### Verification

1. `curl -X POST /api/queue -d '{"wo":"WO-1096","title":"x"}'` → 400
2. Existing Clarion queue WO (e.g. with mount spec) still claimable
3. No engine WOs reappear on Overview after a poll cycle
