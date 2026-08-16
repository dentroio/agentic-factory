---
name: gha-workflows-no-direct-interpolation-untrusted-fields
description: GitHub Actions workflows must pass untrusted fields (PR/issue titles, bodies, LLM/CI outputs) through env vars, never interpolate directly into run/script blocks
metadata:
  type: feedback
---

GitHub Actions `${{ ... }}` expressions referencing untrusted content (PR/issue titles or bodies, CI log excerpts, LLM-generated summaries/reasons like `outputs.fix_summary`, `outputs.claude_reason`, etc.) must never be spliced directly into a `run: |` shell block or `actions/github-script` `script: |` block. A quote or backtick in the value becomes executable shell/JS. Instead, assign the value to an `env:` var and reference it as `$VAR` (shell) or `process.env.VAR` (JS).

**Why:** GitHub Actions expands `${{ }}` before the shell/JS runs, so untrusted text (attacker-controlled PR titles, LLM output) is treated as source code, not data — a classic injection vector (see WO-1063).

**How to apply:** When adding/editing workflows, never write `${{ github.event.pull_request.title }}` or `${{ steps.x.outputs.y }}` inside `run