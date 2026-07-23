# WO-1050 — Oryntra: Factory as an Execution Target in the IDE Registry

**Created:** 2026-07-23
**Priority:** P3
**Effort:** L
**Services:** none at spec time (exploratory; likely touches orchestrator claim flow)
**Repos:** `dentroio/Oryntra`, `dentroio/agentic-factory`
**Depends on:** WO-1047, WO-1048 — and dogfooding both first
**Status:** Open (exploratory — do not dispatch until 1047–1049 are dogfooded)

---

## Background

Oryntra's IDE registry routes approved artifacts to a connected IDE (Cursor, VS Code,
Windsurf) via MCP for a human-driven implementation session. The factory's
agent-runner executes WOs autonomously. For artifacts that don't need a human at the
keyboard, "the factory" should be selectable as the execution target: approve the
artifact, export it as a WO (WO-1048), and let the factory dispatch it — with Oryntra
tracking progress via the WO thread.

## What to Build (exploration scope)

1. **"Factory" pseudo-IDE in the registry** — appears as a routing chip alongside
   real IDEs; health = factory reachability (`GET {FACTORY_URL}/api/factory/dispatch`
   responding). Selecting it as `preferredIde` means handoff = WO-1048 export instead
   of MCP.
2. **Progress readback** — after export, the session shows the WO's dispatch status
   (queued → claimed → in_progress → PR link → awaiting_human) from the dispatch map,
   and thread messages via the WO-1047 client.
3. **Round-trip** — when the WO reaches `awaiting_human`, surface it in the WO-1049
   validation queue, closing the loop: review → artifact → factory build →
   Oryntra validation.
4. **Open questions to resolve in this WO** (write findings into
   `docs/ORYNTRA_FACTORY_INTEGRATION.md`):
   - Should Oryntra be able to pin the exported WO to the front of the factory queue,
     or is queue order strictly the PM's call?
   - Does auto-dispatch need a human approval step distinct from artifact approval
     (factory has pre-dispatch approval, WO-1036)?

## Acceptance Criteria

- [ ] "Factory" appears in the IDE chips only when the factory is reachable
- [ ] Routing an approved artifact to Factory creates the WO (via WO-1048 path) and
      the session shows live dispatch status transitions
- [ ] When the exported WO reaches `awaiting_human`, it appears in the WO-1049 queue
      within one poll interval
- [ ] Open questions above have written answers in the integration doc

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | Oryntra IDE registry (`packages/server`) | "factory" pseudo-IDE + health probe |
| Modify | `packages/review-room/...` | Factory chip, dispatch progress UI |
| Modify | `docs/ORYNTRA_FACTORY_INTEGRATION.md` | Findings on open questions |
