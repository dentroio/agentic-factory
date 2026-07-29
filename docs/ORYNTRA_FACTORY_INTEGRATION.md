# Oryntra ↔ Agentic Factory Integration Program

**Created:** 2026-07-23
**Status:** Proposed
**Repos:** `dentroio/agentic-factory`, `dentroio/Oryntra`
**Work orders:** WO-1047 – WO-1052

---

## Context

Two generations of Oryntra exist:

1. **Legacy annotation extension** (WO-1011, shipped 2026-07-04) — a small Chrome MV3
   extension that captures a tab screenshot, lets the human draw on it, and POSTs it to
   the factory WO thread via the status-site CORS proxy. Lives on the
   `feat/factory-thread-integration` branch of `dentroio/Oryntra` (unrelated git history
   to current `main`). The factory side of this — orchestrator image storage/serving,
   status-site proxy, inline thread rendering — is merged and verified working.

2. **Enterprise Oryntra** (current `main` of `dentroio/Oryntra`) — a full "live AI
   product review room": Chrome extension + side-panel Review Studio, Node/Fastify
   backend on `localhost:4317`, spatial capture (mouse, clicks, element identity,
   screenshots), an LLM facilitator that turns feedback into structured artifacts
   (change requests, doc updates, architecture notes, **work orders**), an IDE registry,
   and MCP handoff to Cursor / VS Code / Windsurf. Phases 0–6 complete.

Enterprise Oryntra has **no factory integration**. Its artifacts hand off to a local
IDE; its evidence stays in its own SQLite. The factory has **no visual feedback
surface** other than the legacy extension. This program wires them together so Oryntra
becomes the factory's human-verification cockpit, and the factory becomes an execution
target for Oryntra's artifacts.

## Factory integration surfaces (all verified live 2026-07-23)

| Surface | Endpoint | Notes |
|---------|----------|-------|
| Post message/screenshot to WO thread | `POST {status-site}/api/proxy/thread/{wo}/messages` | No auth needed; accepts `image_data` base64; orchestrator saves and returns `image_url` |
| Read WO thread | `GET {status-site}/api/thread/{wo}/messages?since=` | Polling path used by thread UI |
| Active WO detection | `GET {status-site}/api/factory/dispatch` | Flat map `{wo_id: {status, claimed_at, ...}}`; active = `claimed` / `in_progress` / `awaiting_human` |
| Create factory WO | `POST {status-site}/api/factory/wos` | Auto-assigns next number from spec files; writes spec file + PLAN entry via GitHub |
| Human validation verdicts | `POST {status-site}/api/validations/{wo}/approve` / `reject` | Proxied to orchestrator with auth header injected |

## Integration architecture

```
Chrome tab (app under review)
   │  spatial capture
Enterprise Oryntra extension + Review Studio side panel
   │
Oryntra backend (localhost:4317)
   │
   ├─ WO binding: session ↔ factory WO        (WO-1047)
   ├─ Evidence relay → WO thread              (WO-1047)
   ├─ Artifact export → factory WO queue      (WO-1048)
   ├─ Validation queue in Review Studio       (WO-1049)
   └─ "factory" as execution target           (WO-1050, exploratory)
   │
Factory status site (localhost:8099) → orchestrator (localhost:8100)
```

Design principles:

- **Oryntra backend talks to the factory, not the extension directly.** The backend
  already owns session state and screenshots; the status-site proxy exists for
  browser-origin calls if needed, but server-to-server is simpler and keeps the
  extension thin.
- **The factory WO thread is the system of record for review evidence.** Oryntra keeps
  its own session store, but anything the human sends to the factory lands in the WO
  thread where agents already read.
- **Artifacts flow one way: Oryntra drafts, factory queues, agents execute.** No
  bidirectional sync of WO state into Oryntra's artifact store — Oryntra reads factory
  state live instead.

## Work order breakdown

| WO | Title | Priority | Repo(s) |
|----|-------|----------|---------|
| WO-1047 | Session ↔ WO binding + evidence relay to factory thread | P1 | Oryntra |
| WO-1048 | Export approved Oryntra work-order artifacts to factory queue | P2 | Oryntra |
| WO-1049 | Factory validation queue in Review Studio | P2 | Oryntra (+ status-site if gaps found) |
| WO-1050 | Factory as execution target in IDE registry | P3 | Oryntra |
| WO-1051 | Retire legacy annotation extension; truth-up docs | P3 | both |
| WO-1052 | Fix WO number reservation counter drift | P2 | agentic-factory |

WO-1052 is not Oryntra work — it is a factory bug found while scoping this program
(`GET /api/plan/next-wo-number` returned `WO-1035` while spec files reach `WO-1046`) —
but it must be fixed before any automation calls that endpoint.

## Sequencing

1. **WO-1047 first** — it delivers the dogfood loop (review a factory-built change in
   Oryntra, feedback lands in the WO thread) and replaces the only thing the legacy
   extension did.
2. WO-1048 and WO-1049 are independent of each other; both depend on 1047's factory
   client module.
3. WO-1050 is exploratory — do not start until 1047–1049 have been dogfooded.
4. WO-1051 anytime after 1047 ships.
5. WO-1052 anytime; before 1048 if 1048's implementation chooses to call the
   reservation endpoint (it should not — `POST /api/factory/wos` numbers from spec
   files and is authoritative).
