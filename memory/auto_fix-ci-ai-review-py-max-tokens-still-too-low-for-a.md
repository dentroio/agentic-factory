---
name: ai-review-max-tokens-undersized
description: scripts/ai_review.py max_tokens has been bumped twice (1500->4096->8192) for truncation failures on normal-sized PRs
metadata:
  type: project
---

`scripts/ai_review.py` calls Claude with a `max_tokens` cap on the review response. This value has repeatedly proven too low: 1500 was bumped to 4096, then 4096 was bumped to 8192, both times because a *normal-sized* feature PR (not an outlier diff) caused the response to be truncated before reaching the required `### Verdict` section. The script treats a missing verdict as unparseable and hard-fails (exit 1) the CI check — so this isn't just a quality issue, it blocks merges.

**Why:** Claude's review responses (analysis + verdict) can run long even for modest diffs, and truncation silently breaks the parse step with no clear "ran out of tokens" signal — it just looks like a failed review.

**How to apply:** If ai_review CI fails with "no verdict found" or similar parse errors, check whether the response was truncated at the token limit before assuming the diff is unusually large or the model behaved badly. Consider whether max_tokens needs another bump, or whether the prompt should ask for a more concise format.