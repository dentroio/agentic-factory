---
name: wo-resolver-branch-first-precedence
description: Branch name is authoritative for WO resolution; title is only a fallback — and extract_wo_from_branch requires the bare ref (no "origin/" prefix or "refs/heads/")
metadata:
  type: project
---

When resolving which Work Order a PR belongs to, the branch name (`head.ref`) always wins over the PR title. This matters when a PR's title mentions a different WO number than its branch (e.g., a developer puts the wrong WO in the title, or the title references a parent WO while the branch is for a child WO).

A non-obvious constraint: `extract_wo_from_branch()` uses `re.match(r"wo/(\d+)-", ...)`, which means the pattern must appear at the **start** of the string. When reading local git branch output (e.g., `git branch -r`), the `"origin/"` prefix must be stripped before calling this function — the orchestrator does `line.strip().removeprefix("origin/")` for exactly this reason. Passing `"origin/wo/1041-slug"` or `"refs/heads/wo/1041-slug"` will return `None` silently.

**Why:** The branch name is set at PR creation time by tooling and reflects the actual WO being worked. PR titles are human-edited and can drift. The regex anchor prevents false positives on refs like `refs/heads/wo/...`.

**How to apply:** Always strip remote prefixes and `refs/heads/` before calling `extract_wo_from_branch()`. Use `resolve_wo_for_pr(pr_dict)` as the single call site whenever you have a full GitHub PR dict — it handles both sources with correct precedence.