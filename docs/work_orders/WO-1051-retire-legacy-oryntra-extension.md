# WO-1051 — Retire the Legacy Oryntra Annotation Extension

**Created:** 2026-07-23
**Priority:** P3
**Effort:** S
**Services:** docs
**Repos:** `dentroio/Oryntra`, `dentroio/agentic-factory`
**Depends on:** WO-1047 (enterprise Oryntra must relay evidence before the legacy path is removed)
**Status:** Open

---

## Background

The legacy annotation extension (WO-1011) lives on `feat/factory-thread-integration`
in `dentroio/Oryntra` — a git lineage **unrelated** to current `main` (which holds
enterprise Oryntra). GitHub refuses a PR between them ("no history in common").
The branch received a fix on 2026-07-23 (commit `83ab15f`: auto-detect now uses
`GET /api/factory/dispatch`; `/api/status` no longer exists) and works today, but it
duplicates what WO-1047 delivers inside enterprise Oryntra.

## What to Build

1. **Archive, don't merge** — after WO-1047 ships and is dogfooded:
   - Tag the branch head: `git tag legacy-annotation-extension 83ab15f` (or current
     head) and push the tag.
   - Add `docs/LEGACY_EXTENSION.md` on Oryntra `main` recording what it was, the tag,
     and that WO-1047 superseded it.
   - Delete the remote branch.
2. **Truth-up factory docs** in `dentroio/agentic-factory`:
   - `docs/project_management/CAPABILITY_STATUS.md` — Dimension 6 table currently
     points at the legacy branch; repoint capabilities to enterprise Oryntra and
     replace Open Gap #4 ("Oryntra not yet merged to main") with the real state:
     legacy lineage archived, enterprise integration tracked by WO-1047–1050.
   - `docs/TECHNICAL_ARCHITECTURE.md` §"Oryntra Chrome Extension" — describe
     enterprise Oryntra + backend relay instead of the legacy direct-POST extension.
   - `docs/wiki/Daily-Workflow.md` — update the Oryntra mention.
3. **Do not remove factory-side WO-1011 plumbing** (orchestrator image storage,
   proxy, thread rendering) — WO-1047 uses exactly these endpoints.

## Acceptance Criteria

- [ ] Legacy branch tagged and deleted; tag resolves to the final commit
- [ ] `docs/LEGACY_EXTENSION.md` exists on Oryntra `main` and names the tag
- [ ] `grep -ri "feat/factory-thread-integration" docs/` in agentic-factory returns
      nothing
- [ ] CAPABILITY_STATUS Open Gaps no longer claim Oryntra is unmerged; Dimension 6
      reflects enterprise Oryntra
- [ ] WO-1011 endpoints untouched (smoke: POST test image through proxy still 200)

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `docs/LEGACY_EXTENSION.md` (Oryntra) | Archive record + tag pointer |
| Modify | `docs/project_management/CAPABILITY_STATUS.md` | Dimension 6 + Open Gap #4 truth-up |
| Modify | `docs/TECHNICAL_ARCHITECTURE.md` | Oryntra section rewrite |
| Modify | `docs/wiki/Daily-Workflow.md` | Update Oryntra mention |
