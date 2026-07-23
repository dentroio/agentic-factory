# WO-1044 — Clarion CI: Auto-Update All Auto-Merge PRs When Main Advances

**Created:** 2026-07-22
**Priority:** P2
**Effort:** S
**Services:** Clarion GitHub Actions
**Depends on:** —
**Status:** ✅ Complete

---

## Background

Clarion's CI currently only auto-updates Dependabot PRs when main advances. Factory-dispatched PRs with `--auto` merge enabled are not updated automatically. Every time any PR merges, all remaining open PRs fall behind and require a manual `gh pr update-branch` call before they can merge.

Observed July 22, 2026: PRs #435, #436, and #438 each required manual update-branch calls 2-3 times in one session as they queued behind each other. Each update-branch triggers a full CI re-run (~5 minutes), adding ~15 minutes of wall-clock delay per PR chain.

This is addressable with a single GitHub Actions workflow in the Clarion repo.

## What to Build

Add `.github/workflows/auto-update-prs.yml` to the Clarion repo:

```yaml
name: Auto-update auto-merge PRs

on:
  push:
    branches: [main]

jobs:
  update-prs:
    runs-on: [self-hosted, clarion-runner]
    permissions:
      pull-requests: write
      contents: write
    steps:
      - uses: actions/checkout@v7
      - name: Update all auto-merge PRs
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh pr list \
            --json number,autoMergeRequest \
            --jq '.[] | select(.autoMergeRequest != null) | .number' \
          | while read pr; do
              gh pr update-branch "$pr" 2>&1 \
                && echo "✅ Updated PR #$pr" \
                || echo "⚠️ PR #$pr: already up to date or has conflict"
            done
```

The `||` ensures a PR with a real merge conflict doesn't abort updates for the rest.

## Acceptance Criteria

- [ ] `.github/workflows/auto-update-prs.yml` exists in Clarion repo
- [ ] Triggers on push to `main`
- [ ] Updates all open PRs with auto-merge enabled
- [ ] PRs with real conflicts log a warning; workflow does not fail
- [ ] After any PR merges to main, remaining auto-merge PRs are updated within ~60s

## Files

- `.github/workflows/auto-update-prs.yml` in the Clarion repo — new

## Notes

This is a Clarion-repo change, not a factory service change. Agent implementing this should work in the Clarion repo, not the factory repo.

## Resolved

Already implemented in Clarion at `.github/workflows/auto-update-prs.yml` prior to this WO being written. The live version exceeds the spec:
- Covers auto-merge PRs **and** Dependabot PRs
- Auto-resolves `PROGRESS.md` conflicts by taking main's version (most common conflict in agent branches)
- Uses `GH_PAT` instead of `GITHUB_TOKEN` so branch pushes trigger downstream CI (GITHUB_TOKEN pushes are treated as bot activity and don't re-trigger CI)
- Logs per-branch warnings on real conflicts; workflow never fails hard
