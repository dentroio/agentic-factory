# WO-370 — Oryntra Integration: Visual UI Feedback via Thread

**Status:** ✅ Done
**Priority:** P2
**Effort:** M
**Services:** orchestrator + status-site + Oryntra (Chrome extension)
**Repos:** `dentroio/agentic-factory`, `dentroio/Oryntra`
**Depends on:** WO-368 (WO thread)

---

## Problem

Text descriptions of visual bugs lose precision. "The button is in the wrong place" is ambiguous. Oryntra wires the browser directly to the factory thread so visual feedback lands with full spatial context.

---

## What Was Built

### Orchestrator — image message support
- `ThreadMessage` extended with `image_data: str = ""` (base64 PNG/JPEG)
- On receipt: saves to `/data/threads/images/{wo}/{timestamp}.png`, sets `image_url` to served path
- New endpoint: `GET /api/thread/{wo}/images/{filename}` — serves stored screenshots

### Status site — CORS proxy
- `POST /api/proxy/thread/{wo}/messages` — forwards Oryntra annotations; browser-safe cross-origin
- `GET /api/proxy/thread/{wo}/images/{filename}` — proxies image bytes from orchestrator

### Oryntra Chrome extension
- `src/content.js` — canvas drawing overlay (circle, arrow, text tools + undo)
- `src/background.js` — service worker for `chrome.tabs.captureVisibleTab()`
- `src/factory.js` — reusable factory API client module
- `popup.html/js` — extension popup with auto-detect active WO from factory
- `options.html/js` — settings page (factory URL, WO, author name)

### Status site — thread UI
- `wo_detail.html` renders `type="image"` messages inline with click-to-expand
- `source_url` shown as attribution below each screenshot
- JS polling path also updated for image type

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | Oryntra annotation POSTs to factory thread within 2s |
| 2 | Screenshot appears inline in the WO thread |
| 3 | Agent receives image message and can act on annotation text |
| 4 | Settings panel for factory URL, WO, and author name |
| 5 | CORS proxy on status site allows Oryntra to post without browser errors |
| 6 | Images persist across container restarts (stored in volume) |

---

## Execution

- **Branch:** `wo/370-oryntra-integration` in `dentroio/agentic-factory`; `feat/factory-thread-integration` in `dentroio/Oryntra`
- **PRs:** #20 (agentic-factory) merged 2026-07-04
