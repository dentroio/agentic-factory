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

The legacy annotation extension (WO-1011) lived on an unrelated git lineage in
`dentroio/Oryntra` (GitHub would not accept a PR onto `main`). That client received
a fix on 2026-07-23 (commit `83ab15f`: auto-detect uses `GET /api/factory/dispatch`)
and is archived as tag `legacy-annotation-extension`.

## What to Build

1. **Archive, don't merge** — after WO-1047 ships and is dogfooded:
   - Tag the lineage head: `git tag legacy-annotation-extension 83ab15f` (done).
   - Add `docs/LEGACY_EXTENSION.md` on Oryntra recording the tag (done on PR #3).
   - Delete the remote legacy branch (done).
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

- [ ] Legacy lineage tagged and deleted; tag `legacy-annotation-extension` resolves to `83ab15f`
- [ ] `docs/LEGACY_EXTENSION.md` exists on Oryntra and names the tag
- [ ] Factory docs no longer name the deleted legacy Oryntra branch; they point at enterprise Oryntra
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
