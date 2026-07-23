# WO-1048 — Oryntra: Export Approved Work-Order Artifacts to the Factory Queue

**Created:** 2026-07-23
**Priority:** P2
**Effort:** M
**Services:** none (work happens in `dentroio/Oryntra`)
**Repos:** `dentroio/Oryntra`
**Depends on:** WO-1047
**Status:** Open

---

## Background

Oryntra's facilitator turns review feedback into structured artifacts, including its
own "work order" artifact type — but those hand off only to a local IDE via MCP. The
factory is where WOs get queued, dispatched, and executed by agents. When a human
approves a work-order artifact in the Review Studio, it should be exportable to the
factory queue with one click, carrying its spatial evidence with it.

## What to Build

In `dentroio/Oryntra`:

1. **Export mapping** — `packages/server/src/factory/export.ts`:
   Map an approved Oryntra work-order artifact to the factory WO draft shape and
   `POST {FACTORY_URL}/api/factory/wos`. Do **not** send a `number` — the endpoint
   auto-assigns the next number from spec files (authoritative; do not use
   `/api/plan/next-wo-number`, see WO-1052).
   - `title` ← artifact title
   - `priority` ← facilitator-suggested, human-editable in the export dialog
     (default P2); must be exactly `P0`–`P3`
   - Body sections per `docs/work_orders/TEMPLATE.md`: Background ← feedback
     narrative; What to Build ← artifact body; Acceptance Criteria ← artifact's
     expected-behavior items (≥3, independently verifiable)
   - Evidence: append a section linking the factory thread messages already relayed
     by WO-1047 (`image_url`s) and the Oryntra session id
2. **Export UI** — "Send to Factory" action on approved work-order artifacts in the
   Review Studio: preview of the mapped spec, editable priority/title, confirm →
   POST → show the created `WO-` id and link to
   `{FACTORY_URL}/wo/{id}` detail page.
3. **Idempotency** — record the created factory WO id on the artifact; re-export is
   blocked with a link to the existing WO.

## Domain Notes

- `POST /api/factory/wos` requires the factory to have `GITHUB_TOKEN`/`GITHUB_REPO`
  configured; it writes the spec file to the repo via GitHub and updates PLAN. A 503
  `"GitHub not configured"` must surface verbatim in the export dialog.
- The endpoint returns 500 with `{"error": ...}` on failure — surface it, do not
  retry (spec file creation is not idempotent server-side).
- Priority strings must be clean `P0`–`P3` — the orchestrator historically mis-sorted
  on decorated strings (see WO-1046).

## Acceptance Criteria

- [ ] Approving a work-order artifact and clicking "Send to Factory" creates a spec
      file in `docs/work_orders/` with the next sequential number (verify file exists
      in repo after export)
- [ ] The created spec contains ≥3 acceptance criteria and links at least one
      relayed thread `image_url` when the session had visual evidence
- [ ] Priority in the created spec is exactly one of `P0|P1|P2|P3`
- [ ] Re-exporting the same artifact does not create a second WO (verify only one
      spec file; UI links to the existing WO)
- [ ] Factory-down and GitHub-unconfigured failures surface in the dialog without
      corrupting artifact state

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `packages/server/src/factory/export.ts` | Artifact → factory WO mapping + POST |
| Modify | `packages/server/src/...artifact model` | `factoryWoId` field for idempotency |
| Modify | `packages/review-room/...artifact UI` | "Send to Factory" action + preview dialog |
