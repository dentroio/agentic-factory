---
name: llm-prompt-untrusted-tool-policy
description: WO/review/CI text is untrusted prompt data; tool permissions are enforced by centralized argv policy
metadata:
  type: project
---

WO-1093 hardened the LLM harness by treating Work Order markdown, rejection reasons,
CI summaries, and review diffs as untrusted data. These are wrapped before prompt
injection, but prompt wording is not the actual permission boundary.

Tool authority lives in `services/agent-runner/tool_policy.py`. Claude argv gets
an explicit allowed-tools list by default; Gemini/Cursor trust flags are also
centralized there. When adding a backend or changing prompt construction, update
the tool-policy layer and its tests, not just the system prompt text.
