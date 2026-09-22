---
name: agent-pr-label-required-for-ci-automation
description: PRs opened by the agent runner must carry the `agent-pr` label or self-healing CI (auto-fix, review applier) silently never runs on them
metadata:
  type: project
---

The `ci-auto-fix.yml` and `ai-review-applier.yml` workflows only trigger on PRs labeled `agent-pr`. This label must be applied to the PR itself (via `gh pr create --label agent-pr` or `gh pr edit --add-label`), not just created as a repo-level label — the runner previously created the label on the repo but never attached it to PRs, so self-healing CI silently never ran on any agent PR.

**Why:** This was a non-obvious gap: `gh label create agent-pr` succeeding gives no signal that PRs aren't actually tagged with it. Nothing failed loudly — CI auto-fix just never engaged.

**How to apply:** When touching PR-creation logic in `services/agent-runner/runner.py`, ensure `pr_create_argv(...)` still passes `--label agent-pr`, and that the fallback/retry path (when label doesn't exist yet, or `gh pr create` fails/succeeds ambiguously) still calls `_add_agent_pr_label(pr_url, ...)` afterward. Also keep `factory_status.py`'s `REQUIRED_LABELS` and `setup_factory.py`'s `ENGINE_LABELS` in sync with `("new-wo", "agent-pr", "pm-sync")