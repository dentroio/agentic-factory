---
name: worktree-diff-must-use-merge-base-not-last-commit
description: Review-chain diff computation must diff against origin/main's merge-base, not HEAD~1..HEAD, or zero-commit branches show unrelated commits
metadata:
  type: project
---

`get_worktree_diff()` in `services/agent-runner/review_chain.py` diffs a WO's worktree against `origin/main`'s merge-base (`git merge-base HEAD origin/main` then diff against that), not `HEAD~1..HEAD`. This was previously broken: if an agent makes zero real commits, the branch's HEAD is just whatever main's tip happened to be when the worktree was created, so `HEAD~1..HEAD` shows some unrelated commit that landed on main last (e.g. a different WO's merge) — reviewers then correctly report "this diff contains unrelated WO-XXX content" when the true state is the agent produced no diff at all. This looked exactly like cross-WO worktree contamination but wasn't.

**Why:** Any future change to diff/review logic that reintroduces "diff against N commits back" instead of "diff against main" will silently reintro