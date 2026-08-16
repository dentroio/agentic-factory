---
name: workflow-concurrency-groups-required
description: All GitHub workflow YAML files must declare a `concurrency:` block; risk-tier-approval.yml must keep cancel-in-progress false
metadata:
  type: project
---

Every `.github/workflows/*.yml` file (except `.template` files) is required to have a top-level `concurrency:` key, enforced by `tests/unit/test_workflow_concurrency.py`. This prevents stacked/overlapping runs of cron, healer, and notifier workflows.

One exception is intentional and tested: `risk-tier-approval.yml` must keep `cancel-in-progress: false` (never `true`). This is because cancelling an in-progress risk-tier approval run mid-flight would be unsafe/incorrect for that workflow's semantics.

**Why:** Non-obvious invariant — a fresh agent adding a new workflow file will fail CI silently later unless they know this test exists and check it locally. Also easy to "fix" risk-tier-approval.yml by flipping cancel-in-progress to true for consistency with other workflows, which is explicitly wrong here.

**How to apply:** When adding/editing any workflow YAML, always include a `concurrency:` block. When touching `risk-tier-approval.yml`, never set `cancel-in-progress: true`. Run `tests/unit/test_workflow_concurrency.py` after workflow changes.