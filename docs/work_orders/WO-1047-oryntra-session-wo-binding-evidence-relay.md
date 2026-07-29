# WO-1047 — Oryntra: Session ↔ Factory WO Binding + Evidence Relay to WO Thread

**Created:** 2026-07-23
**Priority:** P1
**Effort:** M
**Services:** none (work happens in `dentroio/Oryntra`; factory endpoints already exist)
**Repos:** `dentroio/Oryntra`
**Depends on:** —
**Status:** Open

---

## Background

Enterprise Oryntra (Review Studio + backend on `localhost:4317`) captures spatial
feedback and screenshots but keeps them in its own SQLite. The factory's WO thread is
where agents read human feedback. WO-1011 proved the pipeline with the legacy
annotation extension; this WO ports that capability into enterprise Oryntra so a
review session can be bound to a factory WO and every feedback moment the human sends
lands in that WO's thread with visual evidence.

This is the dogfood-critical WO: it closes the loop "agent builds → human reviews in
Oryntra → agent reads feedback from thread."

## What to Build

In `dentroio/Oryntra` (`packages/server` unless noted):

1. **Factory client module** — `packages/server/src/factory/client.ts`:
   - Config: `FACTORY_URL` (default `http://localhost:8099`), stored per-session
     override in session record.
   - `detectActiveWo(): Promise<string | null>` — `GET {FACTORY_URL}/api/factory/dispatch`,
     response is a **flat map** `{wo_id: {status, claimed_at, ...}}` (no
     `dispatch_state` wrapper — that shape is dead). Filter status in
     `["claimed", "in_progress", "awaiting_human"]`, return most recent by
     `claimed_at`, else null.
   - `postThreadMessage(wo, {content, imageBase64?, sourceUrl?, author})` —
     `POST {FACTORY_URL}/api/proxy/thread/{wo}/messages` with body
     `{author, role: "human", type: imageBase64 ? "image" : "text", content,
     image_data: imageBase64, metadata: {source_url, tool: "oryntra"}}`.
     Returns the created message including served `image_url`.
   - `getThreadMessages(wo, since?)` — `GET {FACTORY_URL}/api/thread/{wo}/messages`.

2. **Session binding** — extend the session model with `factoryWo: string | null`.
   - Review Studio side panel: a WO selector showing the bound WO, with
     "Auto-detect" (calls `detectActiveWo`) and manual entry.
   - Persist on the session record.

3. **Evidence relay** — when the human sends a feedback moment in a bound session,
   relay it to the factory thread: annotation/note text as `content`, the associated
   screenshot as `image_data`, page URL as `metadata.source_url`. Relay failures must
   not break the local review flow — queue and retry once, then surface a non-blocking
   warning chip in the Studio.

4. **Thread awareness (read path)** — in a bound session, show the factory thread's
   latest agent messages in a collapsible strip so the human sees agent replies
   without leaving the Studio. Poll `getThreadMessages(wo, since)` on the session's
   existing refresh cadence.

## Domain Notes

- The status-site proxy injects orchestrator auth — Oryntra needs **no factory
  credentials**. Do not add any Vault/API_SECRET plumbing.
- `GET /api/status` does not exist on the status site. The legacy extension broke on
  this; fixed 2026-07-23 on `feat/factory-thread-integration` (commit `83ab15f`) —
  copy the endpoint usage from there, not from any older reference.
- Pipeline verified live 2026-07-23: POST with 1×1 base64 PNG to
  `/api/proxy/thread/WO-ORYNTRA-TEST/messages` → orchestrator saved image, returned
  `image_url`, and `GET /api/proxy/thread/.../images/{filename}` served
  `200 image/png`.
- Do not call `GET /api/plan/next-wo-number` for anything — counter is out of sync
  (WO-1052).

## Acceptance Criteria

- [ ] A review session can be bound to a factory WO via auto-detect (verified against
      a live dispatch entry) and via manual entry
- [ ] Sending a feedback moment with a screenshot in a bound session creates a
      `type: "image"` message in the factory WO thread within 2s, with
      `metadata.tool == "oryntra"` and `metadata.source_url` set (verify via
      `GET /api/thread/{wo}/messages`)
- [ ] The served `image_url` returns `200 image/png` through the status-site proxy
- [ ] Relay failure (factory down) does not block the local review flow — session
      continues, warning surfaced, `curl`-verifiable by stopping the factory container
- [ ] Unbound sessions behave exactly as today (no factory calls — verify with no
      factory network traffic in backend logs)

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `packages/server/src/factory/client.ts` | Factory API client (detect, post, read) |
| Modify | `packages/server/src/...session model/routes` | `factoryWo` binding field + endpoints |
| Modify | `packages/review-room/...` / side panel | WO selector, relay toggle, agent-reply strip |
| Modify | `docs/ARCHITECTURE.md` (Oryntra) | Document factory integration surface |
