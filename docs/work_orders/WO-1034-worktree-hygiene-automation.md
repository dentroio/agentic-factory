# WO-1034 — Worktree Hygiene Automation

**Created:** 2026-07-18
**Priority:** P2
**Effort:** M
**Services:** clarion/scripts, orchestrator
**Depends on:** WO-1026
**Status:** ✅ Done

---

## Background

Over one week of factory operation, the Clarion repo accumulated:
- 20+ stale worktrees in `.worktrees/` pointing to done WOs
- 26+ stale local branches for done WOs
- 8 stale remote branches for done WOs (never deleted after PR merge)

All of this was cleaned up manually in one session. The `make pr-watch` command is supposed to handle cleanup, but it runs only for the current agent's WO — it doesn't clean up other agents' abandoned worktrees or branches.

Additionally, the factory sometimes re-creates empty worktrees for recently-dispatched WOs that the agent abandoned (WO-385, WO-404). When cleaned up, factory re-creates them. The cleanup and re-creation loop is wasteful.

---

## What to Build

### 1. Add `make wt-clean` to Clarion's Makefile

A safe cleanup command that removes stale worktrees:

```makefile
# Remove worktrees for WOs that are merged/done
wt-clean:
	@echo "→ Checking for stale worktrees..."
	@python3 scripts/wt_clean.py --dry-run
	@echo ""
	@read -p "Proceed with cleanup? [y/N] " CONFIRM && [ "$$CONFIRM" = "y" ] && \
		python3 scripts/wt_clean.py --apply || echo "Skipped."
```

### 2. Write `scripts/wt_clean.py`

```python
#!/usr/bin/env python3
"""Remove worktrees and branches for WOs that are done."""
import subprocess, json, sys, re
from pathlib import Path

def get_done_wos() -> set[int]:
    """Return WO numbers with status: done in their claim files."""
    done = set()
    runs_dir = Path("docs/factory/runs")
    for f in runs_dir.glob("WO-*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("status") in ("done", "complete", "completed"):
                done.add(data["wo"])
        except (json.JSONDecodeError, KeyError):
            pass
    return done

def get_all_worktrees() -> list[dict]:
    """Return list of {path, branch, wo_num} for each worktree."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True
    )
    worktrees = []
    current = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
            m = re.search(r'/(\d+)-', current["branch"])
            current["wo_num"] = int(m.group(1)) if m else None
    if current:
        worktrees.append(current)
    return [w for w in worktrees if w.get("wo_num")]

def main():
    dry_run = "--dry-run" in sys.argv
    done_wos = get_done_wos()
    worktrees = get_all_worktrees()

    stale = [w for w in worktrees if w["wo_num"] in done_wos]
    if not stale:
        print("No stale worktrees found.")
        return

    for wt in stale:
        branch = wt["branch"].replace("refs/heads/", "")
        print(f"{'[dry-run] ' if dry_run else ''}Remove: {wt['path']}  (branch: {branch})")
        if not dry_run:
            subprocess.run(["git", "worktree", "remove", "--force", wt["path"]])
            subprocess.run(["git", "branch", "-D", branch], capture_output=True)
            subprocess.run(["git", "push", "origin", "--delete", branch], capture_output=True)

if __name__ == "__main__":
    main()
```

### 3. Add a remote-branch cleanup pass to `pr-watch`

After merging a PR, `pr-watch` already deletes the worktree and local branch. Extend it to also scan for any OTHER stale branches in the remote that match done WOs:

```bash
# After merge cleanup in pr_watch.sh, run a stale branch scan:
echo "→ Scanning for other stale remote branches..."
for branch in $(git branch -r | grep 'origin/wo/' | sed 's|origin/||'); do
    wo_num=$(echo "$branch" | grep -o '[0-9]\+' | head -1)
    if [ -n "$wo_num" ]; then
        claim="docs/factory/runs/WO-${wo_num}.json"
        if [ -f "$claim" ] && grep -q '"status": "done"' "$claim"; then
            echo "  Deleting stale remote branch: $branch"
            git push origin --delete "$branch" 2>/dev/null || true
        fi
    fi
done
```

### 4. Add a monthly hygiene cron to the factory orchestrator

The orchestrator should run a weekly hygiene check:
- Scan target repo for worktrees corresponding to done WOs
- Scan target repo for local/remote branches corresponding to done WOs
- Report counts via status site / Slack
- Auto-delete if count exceeds 5 stale items (with Slack notification)

```python
# In orchestrator.py, weekly hygiene task:
async def _run_hygiene_check() -> None:
    result = subprocess.run(
        ["python3", "scripts/wt_clean.py", "--dry-run"],
        cwd=_target_repo_path, capture_output=True, text=True
    )
    stale_count = result.stdout.count("Remove:")
    if stale_count == 0:
        return
    if stale_count > 5:
        # Auto-clean
        subprocess.run(["python3", "scripts/wt_clean.py", "--apply"], cwd=_target_repo_path)
        await _post_slack(f"🧹 Auto-cleaned {stale_count} stale worktrees/branches from Clarion repo")
    else:
        await _post_slack(f"🧹 Hygiene: {stale_count} stale worktrees found — run `make wt-clean` to remove")
```

---

## Acceptance Criteria

- [ ] `make wt-clean` shows a dry-run list of stale worktrees and prompts before deleting
- [ ] `scripts/wt_clean.py` correctly identifies done WOs from claim files
- [ ] Running `wt_clean.py --apply` removes worktrees, local branches, and remote branches for done WOs
- [ ] `make pr-watch` scans for and removes other stale remote branches after its own merge cleanup
- [ ] Orchestrator runs weekly hygiene check and auto-cleans when > 5 stale items
- [ ] `make smoke-test` passes

## Documentation Required

- [ ] `CLAUDE.md` — add `make wt-clean` to the ops reference section
- [ ] `docs/ops/RUNBOOK.md` — add worktree hygiene section
