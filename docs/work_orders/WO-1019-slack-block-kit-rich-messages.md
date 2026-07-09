# WO-1019 — Slack Block Kit Rich Messages & Action Buttons

**Status:** ✅ Done
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-1016

---

## Problem

The Slack bot posts plain text. When the PM lists WOs or asks "Launch WO-185?",
users type "yes" in free text. This is fragile — the PM may misread the intent.
Slack's Block Kit supports buttons, headers, and structured layouts that make
the interaction faster and unambiguous.

---

## What to Build

### Rich WO list blocks

When the PM returns a WO status list, format it as Block Kit sections:

```
[Header] Ready Work Orders
[Section] WO-185: Syslog Collector Mode [P1 · S]
          Add syslog ingestion to clarion_collector
[Button] ▶ Start with Cursor   [Button] 📋 Details
```

### Dispatch confirmation buttons

When the PM recommends starting a WO, append an interactive Block Kit block
with two buttons:
- **✅ Yes, dispatch** → POSTs `[DISPATCH:WO-NNN:backend]` action to orchestrator
- **❌ Not yet** → dismisses the prompt

### Implementation

- `slack_bot.py`: detect when PM reply contains `[DISPATCH:...]` tag or a WO list;
  convert to Block Kit JSON before posting
- Add `POST /slack/actions` endpoint to orchestrator to handle button payloads
  (Slack sends these to a request URL — requires Socket Mode Interactivity enabled
  in the Slack App settings)
- Update `SLACK_APP_TOKEN` scope to include `connections:write` (already set)
  and add `Interactivity` feature in Slack App config

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | WO list responses render as structured Block Kit sections |
| 2 | Dispatch prompt includes ✅ / ❌ buttons |
| 3 | Clicking ✅ dispatches the WO without user typing |
| 4 | Clicking ❌ dismisses the prompt |
| 5 | Plain text fallback for environments that don't render Block Kit |
