---
name: held-wos-mutations-require-save-held
description: Every mutation of orchestrator's _held_wos set must be paired with a call to _save_held(), or the hold silently doesn't survive an orchestrator restart.
metadata:
  type: project
---

`_held_wos` is an in-memory set that must be explicitly persisted via `_save_held()` after every add/discard. This is easy to miss for automatic quarantine paths (no human in the loop reviewing the code path at the time), as opposed to manual/human-triggered hold endpoints where the pattern is more visible/tested. Two automatic hold sites (auto-hold after 3 cumulative validation rejections, auto-hold after 2x stuck-detection threshold) went unpersisted for a long time before being caught (AF-20).

**Why:** If `_save_held()` is omitted, the WO looks held in the running process but silently re-enters dispatch after any orchestrator restart, since nothing was written to disk — a dangerous silent failure with no error or log signal.

**How to apply:** When adding or reviewing any new code path that adds to or removes from `_held_wos`, grep for existing `_held_wos.add(`/`_held_wos.discard(` call sites and confirm each is immediately followed by `_save_held()`. Treat "adds to _held_wos without _save_held()" as a bug pattern to actively check for in review.