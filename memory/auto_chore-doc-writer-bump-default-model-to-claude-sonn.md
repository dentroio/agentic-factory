---
name: anthropic-model-default-stale-across-codebase
description: The ANTHROPIC_MODEL default is hardcoded in many agent scripts and architecture docs, not just doc_writer.py — a single env var override is never set in .env, docker-compose, or workflow inputs
metadata:
  type: project
---

The `ANTHROPIC_MODEL` environment variable is never set in any deployment surface (`.env`, `docker-compose`, workflow inputs), so every agent script's hardcoded `os.getenv("ANTHROPIC_MODEL", "<fallback>")` fallback is what actually runs in production. The default in `doc_writer.py` was bumped to `claude-sonnet-5`, but the same stale `claude-sonnet-4-6` default exists in a dozen other agent scripts and at least two architecture docs — none of which were touched in this PR.

**Why:** Because no env override is ever injected, the fallback string in each script is the real model selector, not a safety net. Treating it as a fallback leads to silent drift between scripts.

**How to apply:** When touching any agent script that contains `os.getenv("ANTHROPIC_MODEL", ...)`, audit and update the fallback string to the current default model. Also check architecture docs for hardcoded model references. Consider a single shared constant or a repo-level env default to avoid N-place drift.