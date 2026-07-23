# WO-1045 — Rebase Stacked PRs Before Base Branch Deletion

**Created:** 2026-07-23
**Priority:** P1
**Effort:** S
**Services:** GitHub Actions
**Depends on:** —
**Status:** Open

---

## Background

When a stacked PR is merged with `--delete-branch`, GitHub automatically closes any open PRs that have the deleted branch as their base. This is silent: no error, no warning, just a CLOSED state.

Observed 2026-07-23: merging PR #29 (WO-1041, base→main) deleted `wo/1041-single-wo-resolver`. PR #30 (WO-1042) had `wo/1041-single-wo-resolver` as its base and was immediately closed by GitHub. Same happened to PR #31 (WO-1043) when PR #33 (the replacement for #30) was merged.

Result: two PRs had to be manually recreated as #33 and #34, wasting ~30 minutes and adding noise to the PR history.

## Root Cause

GitHub's behavior: deleting a branch that is the base of an open PR auto-closes that PR. This is by design and cannot be configured away. The fix must happen before the deletion.

## Acceptance Criteria

- [ ] When a PR targeting `main` is merged and its head branch is deleted, any open PRs whose **base** is the deleted branch have their base updated to `main` before the deletion
- [ ] The rebased PRs remain open and their CI re-triggers automatically
- [ ] No PRs are silently closed due to base branch deletion
- [ ] The fix works for chains of any depth (A→B→C: merging A should rebase both B and C if they're still stacked)

## Implementation

Add a GitHub Actions workflow `.github/workflows/rebase-stacked-prs.yml` that triggers on `pull_request` closed+merged events targeting `main`:

```yaml
on:
  pull_request:
    types: [closed]
    branches: [main]
```

Steps:
1. On merge, extract the head branch name (the branch being deleted)
2. Query GitHub API for open PRs whose `base` equals the just-merged head branch
3. For each found PR: call `PATCH /repos/{repo}/pulls/{number}` with `{"base": "main"}` to retarget it
4. Post a comment on each retargeted PR explaining what happened

The base retarget must happen **before** the branch is deleted. Since `--delete-branch` in `gh pr merge` deletes immediately, the workflow must race the deletion. Use the `pull_request` event (fires on merge, before branch deletion settles) — in practice the API retarget is fast enough.

Alternatively, the workflow can simply retarget even after deletion — GitHub allows changing the base of a closed PR, but only if it was closed by the base deletion. Test this path too.

## Files

- `.github/workflows/rebase-stacked-prs.yml` — new

## Notes

This does not require any Python or service code — pure GitHub Actions + `actions/github-script`.

The check for "stacked PRs" is `pr.base.ref == deleted_branch_name` on open PRs.
