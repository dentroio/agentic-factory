---
name: memory-index-auto-populated
description: MEMORY.md indexing is now automatic in memory_agent.py — don't rely on manual index steps in PR templates
metadata:
  type: project
---

MEMORY.md (the discoverable index of lessons) was write-only for weeks: memory_agent.py wrote 14 substantive memory/*.md files but MEMORY.md never pointed at them, because the workflow relied on a human manually adding an index pointer during PR review — a step that was silently skipped every single time, not a one-off oversight. This is now fixed structurally: `append_to_memory_index()` in scripts/memory_agent.py parses the new memory file's frontmatter (name/description/type) and inserts a pointer under the matching MEMORY.md section (`_SECTION_BY_TYPE`) in the same run that writes the file, and post-merge-memory.yml commits both files together.

**Why:** Any workflow step that says "a human should manually do X during review" as its only enforcement mechanism will be skipped indefinitely — there's no reviewer checklist that reliably catches it. This is the second time this exact pattern ("missing file/step means silent failure, not a clear error") was found and fixed in this codebase in one session (also see the ai-review.yml ENOENT fix in the same PR, and the earlier observability.yml fix).

**How to apply:** If you add a new workflow step whose correctness depends on a human doing a manual follow-up action, treat that as a bug waiting to happen — automate it instead. Also, when reading `message.content