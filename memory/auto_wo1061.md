---
name: reviewer-auto-approve-gate-af17
description: Reviewer auto-approval logic (may_auto_approve) and untrusted-diff wrapping are safety invariants (AF-17), not implementation details to casually change
metadata:
  type: project
---

The AI reviewer (`services/agent-runner/reviewer.py`) only auto-approves work when `may_auto_approve(priority, has_ui, has_api_surface)` returns True — which requires priority to be exactly "P2" or "P3" (case-insensitive) AND no UI/API-surface changes. Missing, empty, or unrecognized priority values default to `False` (human gate stays on) rather than defaulting to auto-approve.

Additionally, the raw PR diff passed into the Claude review prompt is wrapped with `wrap_untrusted()` from `prompt_builder.py` before being embedded in the prompt, specifically to prevent a malicious/hostile diff from containing prompt-injection text that could trick the model into emitting an APPROVE verdict.

**Why:** This is the P0/P1 human-safety gate (tracked as AF-17). It was previously possible for backend-only PRs to auto-approve regardless of