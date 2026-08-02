---
name: yaml-workflow-js-template-literal-indentation
description: JS multi-line template literals inside GitHub Actions workflow YAML (github-script steps) break YAML parsing if interior lines aren't indented consistently
metadata:
  type: feedback
---

In `.github/workflows/*.yml` steps using `actions/github-script`, embedding a JS template literal (backtick string) with multiple lines directly in the YAML `script: |` block is dangerous: YAML's block-scalar parser requires all lines to maintain a minimum indentation, and unindented interior lines (common when a template literal is written left-aligned inside indented YAML) cause the block scalar to end early. This silently corrupts the workflow YAML and caused 4 workflow files (ci-auto-fix, ai-review-applier, ci-failure-notifier, rebase-stacked-prs) to fail on every push before running a single step — the failure wasn't caught until PRs surfaced it.

**Why:** YAML doesn't