# WO-1026 — Auto-Mark-Done: Update Claim File and Spec on PR Merge

**Created:** 2026-07-18
**Priority:** P1
**Effort:** M
**Services:** pr-watchdog, orchestrator
**Depends on:** WO-1024
**Status:** ✅ Done

---

## Background

When a PR merges in the target project (e.g. Clarion), three things need to happen to keep the factory in sync:

1. The claim file (`docs/factory/runs/WO-NNN.json`) needs `status: done` and `completed_at`
2. The WO spec file needs `**Status:** ✅ Done` and a `## Merged` section with the PR number
3. The orchestrator's dispatch state needs the entry marked `complete`

Currently none of these happen automatically. Every merged WO requires a manual docs PR, which takes time, is often deferred, and creates a window where the factory sees stale data and may re-dispatch.

In the week ending 2026-07-18, we manually updated 14+ claim files and created multiple batch docs PRs just to catch up — all work that should have been automatic.

The pr-watchdog service already monitors PR state. This WO extends it to push a commit to the target repo's main branch when a PR merges, updating both the claim file and the spec.

---

## What to Build

### 1. Extend `watchdog.py` to detect WO number from merged PR

When a PR's `merged_at` becomes non-null:
```python
import re

def _extract_wo_number(pr_title: str) -> int | None:
    m = re.search(r'WO-(\d+)', pr_title, re.IGNORECASE)
    return int(m.group(1)) if m else None
```

### 2. Push a mark-done commit to the target repo on merge

When a WO PR merges, the watchdog should:

1. Clone (or use existing checkout of) the target repo
2. Run `python3 scripts/mark_wo_done.py --wo WO-NNN --pr NNN --merged-at <ISO>` against it
3. Commit the resulting spec and claim file changes
4. Push directly to `main` (this is a P3 docs-only change — no review needed per risk tier rules)

```python
async def _handle_pr_merged(pr: dict, repo_path: Path) -> None:
    wo_num = _extract_wo_number(pr["title"])
    if not wo_num:
        print(f"[watchdog] merged PR #{pr['number']} has no WO number — skipping mark-done")
        return

    result = subprocess.run(
        ["python3", "scripts/mark_wo_done.py",
         "--wo", f"WO-{wo_num}",
         "--pr", str(pr["number"]),
         "--merged-at", pr["merged_at"]],
        cwd=repo_path, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[watchdog] mark_wo_done failed for WO-{wo_num}: {result.stderr}")
        return

    # Commit and push
    subprocess.run(["git", "add", "docs/factory/runs/", "docs/project_management/work_orders/"],
                   cwd=repo_path)
    subprocess.run(["git", "commit", "-m",
                    f"docs(pm): auto-mark WO-{wo_num} done — PR #{pr['number']} merged"],
                   cwd=repo_path)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo_path)
    print(f"[watchdog] WO-{wo_num} marked done and pushed to main")
```

### 3. Also notify the orchestrator to mark the dispatch entry complete

After the commit, call `POST /api/wos/WO-NNN/complete` (or update `_dispatch_state` directly if watchdog runs in-process) so the orchestrator doesn't wait for its next poll cycle.

### 4. Handle the case where mark_wo_done.py finds no spec file

If no spec file exists for the WO, `mark_wo_done.py` should create a minimal stub spec with title from the PR and `Status: ✅ Done`. Add this fallback to `mark_wo_done.py`:

```python
if not spec_files:
    # Create minimal stub
    stub_path = wo_dir / f"{wo_slug}-auto.md"
    stub_path.write_text(f"# {wo_id} — {pr_title}\n\n**Status:** ✅ Done\n\n## Merged\n\nPR #{pr_num} — {merged_at[:10]}\n")
    print(f"Spec stub created: {stub_path.name}")
```

### 5. Guard against pushing broken state

Before pushing, verify:
- `git status` shows only expected files (claim + spec)
- No untracked files that shouldn't be committed
- The commit message matches the pattern

If any check fails, log the error and skip the push rather than pushing broken state.

---

## Acceptance Criteria

- [ ] When a WO PR merges, watchdog automatically commits updated claim file and spec to `main` within 5 minutes of merge
- [ ] Claim file gets `status: done`, `completed_at`, `pr` fields set correctly
- [ ] Spec file gets `Status: ✅ Done` and `## Merged` section
- [ ] If no spec file exists, a minimal stub is created
- [ ] Orchestrator dispatch entry is marked `complete` after the push
- [ ] PRs with no `WO-NNN` in title are skipped gracefully (logged, not errored)
- [ ] Push failures are logged and do not crash the watchdog
- [ ] `make smoke-test` passes

## Documentation Required

- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — auto-mark-done flow diagram; pr-watchdog responsibilities section
- [ ] Update `AGENT_PROCESS.md` in the factory template — note that manual mark-done is only needed if watchdog is not deployed
