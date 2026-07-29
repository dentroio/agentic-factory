# WO-1049 — Oryntra: Factory Validation Queue in the Review Studio

**Created:** 2026-07-23
**Priority:** P2
**Effort:** M
**Services:** none (work happens in `dentroio/Oryntra`; verify status-site endpoints suffice)
**Repos:** `dentroio/Oryntra` (+ `dentroio/agentic-factory` only if endpoint gaps found)
**Depends on:** WO-1047
**Status:** Open

---

## Background

When a factory WO reaches `awaiting_human`, the human today finds out via the
dashboard or notifications, opens the WO detail page, inspects, and approves or
rejects. Oryntra is precisely the tool for that inspection — it can drive the running
app and capture evidence. Surfacing the factory's validation queue inside the Review
Studio turns "awaiting_human" into a one-click review session.

## What to Build

In `dentroio/Oryntra`:

1. **Queue view** — in the Review Studio side panel, a "Factory validations" section
   listing WOs whose dispatch status is `awaiting_human`
   (from `GET {FACTORY_URL}/api/factory/dispatch`), showing WO id, slug, agent,
   PR link if present.
2. **One-click review session** — selecting an entry starts (or rebinds) a session
   bound to that WO (reuses WO-1047 binding), so evidence captured during
   verification relays to the WO thread automatically.
3. **Verdict actions** — Approve / Reject buttons:
   - `POST {FACTORY_URL}/api/validations/{wo}/approve` or `/reject` with
     `{decided_by: <author name from Oryntra config>, note: <optional text>}`.
   - On reject, prompt for a note (required) — it should reference the evidence
     already relayed to the thread.
4. **Refresh** — the queue refreshes on the session cadence; verdict removes the
   entry optimistically and reconciles on next poll.

## Domain Notes

- The status site injects orchestrator auth on the validation proxies — no
  credentials in Oryntra.
- The proxy defaults `decided_by` to `"human"` — always send the configured author
  name so factory attribution stays meaningful.
- Verify what the orchestrator does with `note` on approve/reject; if it is dropped,
  post the note to the WO thread via the WO-1047 client instead, and record the
  endpoint gap in this WO's PR description for a follow-up factory-side WO.

## Acceptance Criteria

- [ ] A WO in `awaiting_human` appears in the Studio queue within one poll interval
      (verify by driving a dispatch entry to `awaiting_human` and polling)
- [ ] Approve from Oryntra results in the same orchestrator state change as approve
      from the dashboard (compare `GET /api/factory/dispatch` entry after each)
- [ ] Reject requires a note, and the note is durably visible in factory state — via
      the validation record or as a thread message
- [ ] `decided_by` in factory records equals the Oryntra-configured author name, not
      the default `"human"`
- [ ] With the factory unreachable, the queue section shows an offline state and the
      rest of the Studio is unaffected

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `packages/server/src/factory/client.ts` | Add validation-queue read + verdict calls |
| Modify | `packages/review-room/...side panel` | Queue section, verdict UI, reject-note prompt |
