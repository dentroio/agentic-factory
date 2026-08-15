---
name: wrap-untrusted-content-in-agent-prompts
description: Any WO markdown, rejection reason, CI analysis, or other externally/attacker-influenced text embedded in agent prompts must go through prompt_builder.wrap_untrusted()
metadata:
  type: project
---

WO specs, reviewer rejection reasons, and CI failure analysis are attacker-controlled relative to the agent-runner's process instructions (AF-16 threat model): anyone who can influence a work order or CI output can inject prompt instructions into the agent's context. `services/agent-runner/prompt_builder.py` has a `wrap_untrusted()` helper that frames such text as "DATA, not instructions" and strips the sentinel delimiter strings (`UNTRUSTED_BEGIN`/`UNTRUSTED_END`) from the payload first, so injected content can't forge a fake closing tag to escape the wrapper.

**Why:** Without stripping sentinels, an attacker could include the literal `<<<END_UNTRUSTED_FACTORY_DATA>>>` string in a WO description or rejection reason to prematurely close the untrusted block and inject trusted-looking instructions afterward.

**How to apply:** When adding any new field to the agent prompt that originates from a WO, PR comment, CI output, human rejection, or other non-agent-runner-controlled source, wrap it with `wrap_untrusted(label, text)` rather than interpolating it directly into the prompt string.