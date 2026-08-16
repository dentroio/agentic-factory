---
name: risk-tier-workflow-no-cancel-in-progress
description: The risk-tier-approval required check workflow must never use cancel-in-progress:true, and its label-check script polls briefly to avoid races
metadata:
  type: project
---

The `risk-tier-approval.yml` GitHub Actions workflow (required status check gating P0/P1 merges) triggers on both `opened` and `labeled` PR events. If its concurrency group has `cancel-in-progress: true`, a later run (e.g. triggered by adding the `risk-tier-approved` label) cancels the earlier `opened` run — but GitHub reports the *cancelled* run's conclusion for the required check, which blocks merge even though the newer