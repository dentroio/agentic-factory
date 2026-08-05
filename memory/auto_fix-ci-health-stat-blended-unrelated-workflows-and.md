---
name: ci-health-stat-scoping-and-skip-handling
description: list_ci_runs() returns unfiltered workflow runs; any stat built on it must filter by workflow name and exclude skipped/cancelled runs
metadata:
  type: project
---

`list_ci_runs()` (services/status-site/main.py) hits `/actions/runs` with no workflow filter, so it returns runs from *every* workflow in the repo — CI Auto-Fix, the Dependabot bridge, the automation watchdog, "Documentation", etc. — not just the actual CI gate. Any stat labeled "CI Health" or similar must explicitly filter `r.get("name") == "CI"` (or whatever the real gate workflow is named) before aggregating.

Additionally, `conclusion == "skipped"` (and `"cancelled"`) must be excluded from both numerator and denominator when computing pass rates. A workflow that correctly skips because its trigger condition wasn't met (e.g. no failure to auto-fix, no dependabot PR to bridge) is not a failure — including it in the denominator without counting it as a pass silently deflates the percentage.

**Why:** This caused a live dashboard to show "CI Health: 40%" for a repo whose actual CI gate was passing on every recent PR — 12 of 20 sampled runs were unrelated automation workflows correctly skipping, not CI failures.

**How to apply:** Whenever adding/modifying a stat derived from `list_ci_runs()` or similar GitHub Actions run listings