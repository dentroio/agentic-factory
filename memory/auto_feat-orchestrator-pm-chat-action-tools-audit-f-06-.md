---
name: pm-chat-dual-action-mechanisms
description: PM chat has two coexisting action-triggering mechanisms (regex tags and Anthropic tool-calling) that must stay in sync
metadata:
  type: project
---

PM chat actions (dispatch, reset, PR merge, dependabot actions, program/phase/milestone CRUD) are triggered by **two parallel mechanisms that both must keep working**: (1) a regex parser that strips bracketed tags like `[DISPATCH:WO-NNN:backend]` from the model's prose reply, and (2) real Anthropic tool-calling (`_PM_ACTION_TOOLS` + `_execute_pm_tool`). The regex parser is not legacy cruft to be deleted — it's the *only* action mechanism available when PM chat falls back to a non-Anthropic (e.g. CLI) backend, since that path is plain text Q&A with no tool support. On the Anthropic API path both are technically live, but the system prompt tells the model to call tools instead of emitting tags, so the regex just finds nothing to strip (a no-op safety net in case the model slips back to bracket-tag prose).

**