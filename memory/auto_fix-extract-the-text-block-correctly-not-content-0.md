---
name: anthropic-text-block-extraction
description: Never use message.content[0].text to extract Claude API response text — must scan for the text-type block
metadata:
  type: project
---

Anthropic Messages API responses can return a `ThinkingBlock` (extended thinking) as `content[0]` before the actual text block, depending on model (e.g. observed with claude-sonnet-5 but not sonnet-4.6). Any code doing `message.content[0].text` will crash with `AttributeError: 'ThinkingBlock' object has no attribute 'text'` for such models, and this is NOT caught by unit tests since they mock the API and don't exercise real responses.

**Why:** This was live-broken on main across all 11 call sites (scripts/*.py and services/orchestrator/*.py) after a prior PR switched default models to sonnet-5, undetected because no test hits the real Anthropic API. It was also likely the true cause of a previously-observed "max_tokens truncation" symptom (thinking tokens eating the budget looks like truncation but isn't).

**How to apply:** Always extract text via `next(b.text for b in message.content if b.type == "text")` instead of indexing `content[0]`. When adding any new Anthropic API call site, use this pattern from the start, and consider adding an integration test (real or recorded response) that includes a ThinkingBlock to catch regressions, since unit tests with mocks won't.