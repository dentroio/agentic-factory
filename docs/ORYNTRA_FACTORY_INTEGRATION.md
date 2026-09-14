# Oryntra ↔ Agentic Factory Integration Program

**Created:** 2026-07-23
**Status:** In progress (WO-1047 on Oryntra `main`; WO-1048–1051 on Oryntra PR #3)
**Repos:** `dentroio/agentic-factory`, `dentroio/Oryntra`
**Work orders:** WO-1047 – WO-1052

---

## Context

Two generations of Oryntra existed:

1. **Legacy annotation extension** (WO-1011, shipped 2026-07-04) — a small Chrome MV3
   extension that captured a tab screenshot, let the human draw on it, and POSTed it to
   the factory WO thread via the status-site CORS proxy. That client lived on an
   unrelated git lineage and is **archived** as tag `legacy-annotation-extension`
   (commit `83ab15f`). The factory side — orchestrator image storage/serving,
   status-site proxy, inline thread rendering — stays; enterprise Oryntra uses it.

2. **Enterprise Oryntra** (`main` of `dentroio/Oryntra`) — live AI product review:
   Chrome extension + side-panel Review Studio, Node/Fastify backend on
   `localhost:4317`, spatial capture, facilitator artifacts, IDE registry, MCP
   handoff, and factory bind / export / validation / execution-target (WO-1047–1050).

Oryntra is the factory's human-verification cockpit. The factory is an execution
queue for Oryntra artifacts (Send to Factory), not a subprocess of Oryntra.

## Factory integration surfaces (all verified live 2026-07-23)

| Surface | Endpoint | Notes |
|---------|----------|-------|
| Post message/screenshot to WO thread | `POST {status-site}/api/proxy/thread/{wo}/messages` | Requires `Authorization: Bearer <API_SECRET>` (or a same-origin browser Origin); accepts `image_data` base64; orchestrator saves and returns `image_url` |
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
| WO-1052 | Fix WO number reservation counter drift ✅ Done | P2 | agentic-factory |

WO-1052 is not Oryntra work — it is a factory bug found while scoping this program
(`GET /api/plan/next-wo-number` returned `WO-1035` while spec files reach `WO-1046`).

**✅ Done, 2026-07-30 — but the root cause was not what it looked like.** It was never
a stale counter. `GITHUB_REPO`/`WO_PATH` were hardcoded to Clarion, so the endpoint had
no notion of "which repo" and always numbered against Clarion's WO space — it happened
to answer with Clarion's own WO-1035 rather than a made-up number. Fixed by making
`/api/wos/reserve` repo-scoped (optional `repo`/`wo_path`, default unchanged). See
[Technical Architecture](TECHNICAL_ARCHITECTURE.md) ("WO number reservation is
repo-scoped") and the [WO-1052
spec](work_orders/WO-1052-fix-wo-number-reservation-drift.md) for the full writeup,
including a second bug (completed-but-spec-file-less dispatch entries from Clarion's
own history inflating "next" to 1036 instead of 442) caught during verification.

## Sequencing

1. **WO-1047 first** — it delivers the dogfood loop (review a factory-built change in
   Oryntra, feedback lands in the WO thread) and replaces the only thing the legacy
   extension did.
2. WO-1048 and WO-1049 are independent of each other; both depend on 1047's factory
   client module.
3. WO-1050 is exploratory — do not start until 1047–1049 have been dogfooded.
4. WO-1051 anytime after 1047 ships.
5. ~~WO-1052 anytime; before 1048 if 1048's implementation chooses to call the
   reservation endpoint~~ — done; moot either way, `POST /api/factory/wos` remains
   the authoritative numbering path and 1048 should still use that, not the
   reservation endpoint.

## WO-1050 findings (2026-09-13)

**Factory as execution target.** A **Factory** chip appears in Oryntra's IDE registry
only while `GET {FACTORY_URL}/api/factory/dispatch` returns OK. Selecting it sets
`preferredIde=factory`: Approve still does not create a WO; handoff is **Send to
Factory** (WO-1048). MCP implement is skipped. Live dispatch (queued → claimed →
in_progress → PR → `awaiting_human`) shows on the bound session; `awaiting_human`
feeds the WO-1049 validation queue.

**Queue pin.** Oryntra does **not** pin exported WOs to the front of the factory
queue. Order is the factory PM's call (`ORDER BY position ASC`; new rows append at
`max(position)+10`). Pinning from Review Studio would bypass the dashboard.

**Auto-dispatch vs artifact approval.** Two distinct gates:

1. Oryntra **Approve** — review-only. Does not start Cursor and does not queue a WO.
2. Oryntra **Send to Factory** — creates the WO. Factory **pre-dispatch approval**
   (WO-1036 / `REQUIRE_APPROVAL_FOR`, default P1) remains a factory-side gate after
   the row exists, then an idle runner claims it.
