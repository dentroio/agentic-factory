# WO-1028 — Clarion: wo-start Branch Divergence Guard

**Created:** 2026-07-18
**Priority:** P1
**Effort:** S
**Services:** clarion/scripts/wo_start.sh
**Depends on:** none
**Status:** ✅ Done

---

## Background

When two or more agents work in parallel, a second agent's worktree may be created from a point before the first agent's PR merged. The second agent then develops against stale main. When its PR is opened, `git diff origin/main..wo/NNN` includes all of the first agent's changes as **regressions** in the diff — the reviewer sees hundreds of lines being removed that were actually already on main.

This happened with WO-199: cursor's branch was based on main before WO-198 merged. The diff showed pxgrid_client.py changes being reverted. The fix required resetting the branch to current main and re-implementing from scratch — several hours of wasted work.

`wo_start.sh` currently does `git checkout -b wo/NNN-slug origin/main` which is correct at creation time. The problem is when the worktree already exists (restarted agent, human continuing work) — the existing branch may be stale. Additionally, before doing any implementation work, an agent should verify it is still based on the most recent main.

---

## What to Build

### 1. Add a divergence check to `wo_start.sh`

After creating or switching to the worktree branch, check that it is based on current `origin/main`:

```bash
# Fetch latest main
git fetch origin main --quiet

MERGE_BASE=$(git merge-base HEAD origin/main)
MAIN_TIP=$(git rev-parse origin/main)

if [ "$MERGE_BASE" != "$MAIN_TIP" ]; then
    COMMITS_BEHIND=$(git rev-list --count "$MERGE_BASE..origin/main")
    echo ""
    echo "⚠️  WARNING: This branch is $COMMITS_BEHIND commit(s) behind origin/main."
    echo "   Merge base: $MERGE_BASE"
    echo "   main tip:   $MAIN_TIP"
    echo ""
    echo "   Other WOs have merged since this branch was created."
    echo "   You MUST rebase before implementing to avoid reverting merged work:"
    echo ""
    echo "     git rebase origin/main"
    echo ""
    echo "   If rebase conflicts: git rebase --abort, then git merge origin/main --no-edit"
    echo ""
    read -p "   Type 'rebase' to run git rebase now, or press Enter to continue anyway: " CHOICE
    if [ "$CHOICE" = "rebase" ]; then
        git rebase origin/main
        echo "✅ Rebase complete."
    else
        echo "⚠️  Continuing without rebase — make sure to rebase before opening your PR."
    fi
fi
```

### 2. Add a pre-commit check for divergence

Add a git pre-commit hook (installed by `pre-commit install`) that warns if the branch is more than 5 commits behind main at commit time:

```bash
#!/usr/bin/env bash
# .git-hooks/pre-commit-divergence
BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
if [ "$BEHIND" -gt 5 ]; then
    echo "⚠️  Your branch is $BEHIND commits behind origin/main."
    echo "   Run: git rebase origin/main  before this commit to avoid merge conflicts."
    echo "   (This is a warning, not a block — commit will proceed)"
fi
```

This is a warning only (exit 0) — it does not block the commit but makes the situation visible.

### 3. Add divergence detection to AGENT_PROCESS.md

Add a step between "Sync first" and "Create the branch":

> **Before implementing anything:** verify your branch is based on current main.
> ```bash
> git fetch origin main
> git rebase origin/main   # if you see "N commits behind"
> ```
> If `git diff origin/main..HEAD` shows files being removed that shouldn't be — you are reverting merged work. Stop, rebase, and re-verify the diff.

---

## Acceptance Criteria

- [ ] `wo_start.sh` fetches `origin/main` and computes the merge-base on every run
- [ ] If branch is behind main, a clear warning is printed with the commit count
- [ ] User is prompted to rebase interactively; entering `rebase` runs `git rebase origin/main`
- [ ] Pre-commit hook warns (non-blocking) when branch is more than 5 commits behind main
- [ ] `AGENT_PROCESS.md` updated with divergence check step
- [ ] Existing `make wo-start` behavior is unchanged when branch is current

## Documentation Required

- [ ] `AGENT_PROCESS.md` in Clarion — add divergence check step to execution flow
