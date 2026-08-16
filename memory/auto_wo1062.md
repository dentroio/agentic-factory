---
name: ai-review-untrusted-data-wrapping
description: scripts/ai_review.py must wrap any attacker-controlled text (PR diff, description, etc.) with wrap_untrusted(), never raw markdown fences
metadata:
  type: project
---

`scripts/ai_review.py` treats the PR diff (and similarly untrusted PR-supplied text) as prompt-injection risk (tracked as AF-17). A prior version embedded the diff inside a ```` ```diff ... ``` ```` markdown fence; an attacker could include a closing fence in the actual diff content to break out and inject fake instructions into the reviewer prompt.

The fix introduced `wrap_untrusted(label, text)` which strips backtick fences and the sentinel markers (`<<<BEGIN_UNTRUSTED_FACTORY_DATA>>>` / `<<<END_UNTRUSTED_FACTORY_DATA>>>`) from the payload before wrapping it, so the payload can never forge its own sentinel boundaries.

**Why:** Any untrusted content interpolated into an LLM prompt (CI diffs, PR descriptions, user-controlled build output, etc.) must not use a del