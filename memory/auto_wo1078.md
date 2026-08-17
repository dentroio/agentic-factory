---
name: path-traversal-guard-pattern-thread-store
description: Any endpoint that builds filesystem paths from user-supplied IDs (WO ids, filenames) must validate with thread_store.require_wo_id/require_image_filename/contained_path, not raw f-string joins
metadata:
  type: project
---

Filesystem paths built from user-supplied identifiers (WO ids, image filenames) in the orchestrator must never be constructed via direct f-string/Path joins like `DATA_DIR / "threads" / "images" / wo / filename` — this was a path-traversal vuln (AF-28/WO-1078) allowing `..` segments to escape the data dir.

**Why:** WO ids and filenames come straight from URL path params with no prior validation; a value like `../../etc/passwd` or `WO-1/../../x` would resolve outside the intended directory before this fix.

**How to apply:** For any new route or function that takes a WO id or filename and joins it into a path, use `thread_store.require_wo_id()` / `thread_store.require_image_filename()` to normalize/validate the raw string, then `thread_store.contained_path(root, *parts)` to join and verify the result via `Path.is_relative_to(root)`. Catch `thread_store.UnsafePath` and return HTTP 400. Don't reintroduce raw `Path(...) / user_value` joins for thread storage or similar per-WO file storage.