---
name: ci-gates-must-fail-closed-single-verdict-step
description: CI/gate workflows in this repo must have exactly one final "verdict" step that always runs and denies by default; skip-flags and job-level `if:` conditions are bypasses
metadata:
  type: project
---

The AI review gate (and any similar required-check workflow) had multiple failure modes that all reduced to the same bug: a step being skipped/never-reached made the job report success, because only the reviewer's own outcome (not "did the reviewer run at all") gated the job.

**Why:** GitHub Actions treats a skipped job/step as pass