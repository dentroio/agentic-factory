---
name: risk-tier-approval-not-yet-required
description: New risk-tier approval gate (AF-01) exists but is NOT registered as a required GitHub ruleset status check yet
metadata:
  type: project
---

`.github/workflows/risk-tier-approval.yml` (running `scripts/check_risk_tier_approval.py`) was merged but deliberately left as a non-required check. It will run and report on PRs but cannot yet block a merge. Do not assume P0/P1 approval is actually enforced in CI until someone promotes it to a required status check on the ruleset after verifying it behaves correctly on real PRs.

**Why:** Registering a misbehaving required check immediately would block all merges, including legitimate P2/P3 auto-merges. The team wanted a burn-in period first.

**How to apply:** Before relying on "P0/P1 requires approval" as an enforced invariant, check whether `risk-tier-approval` has been added to the branch protection ruleset's required status checks. Also note: GitHub rulesets' `required_approving_review_count` applies uniformly to all PRs — it cannot be used for tier-specific gating, hence this separate script-based approach. The gate trusts the WO spec's self-declared `**Priority:**` field with no verification against the actual diff (a known gap, tracked under AF-17).