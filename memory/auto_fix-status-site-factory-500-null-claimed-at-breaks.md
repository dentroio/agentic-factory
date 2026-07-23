---
name: null-vs-missing-dict-keys-python
description: In Python, dict.get(key, default) does NOT use the default when the key exists with a null/None value — only when the key is absent
metadata:
  type: feedback
---

`dict.get("key", fallback)` only returns `fallback` when the key is **absent** from the dict. If the key exists but its value is `None` (e.g., a JSON field explicitly set to `null`), `.get()` returns `None`, not the fallback. This silently breaks comparisons like `sorted()` that can't mix `None` and `str`.

**Why:** The status-site `/factory` endpoint crashed with a 500 because work orders from the API can have `claimed_at: null` (key present, value null), not just a missing `claimed_at` key. The default `""` in `.get("claimed_at", "")` was never reached.

**How to apply:** When sorting or comparing fields from external data (API responses, DB rows, JSON), use `w.get("field") or ""` (or `w.get("field") or 0` for numerics) instead of `w.get("field", default)` to safely handle both missing keys and explicit null values.