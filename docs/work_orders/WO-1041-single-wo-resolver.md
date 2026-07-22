# WO-1041 — Single WO Resolver

**Created:** 2026-07-22
**Priority:** P1
**Effort:** M
**Services:** orchestrator, pr-watchdog, status-site
**Depends on:** —
**Status:** Open

---

## Background

WO identity is resolved by regex in at least six places, each slightly differently:

| Location | Method | Field |
|----------|--------|-------|
| `orchestrator.py:2471` `_fetch_open_pr_wos()` | `re.search(r"WO-(\d+)", title)` | title only |
| `orchestrator.py:2605` `_fetch_recently_merged_wo_prs()` | `re.match(r"wo/(\d+)-", head_ref)` | branch only |
| `orchestrator.py:4487` | `re.search(r"WO-(\d+)", title)` | title only |
| `pr-watchdog/watchdog.py:58` `_extract_wo_number()` | `re.search(r"WO-(\d+)", title)` | title only |
| `status-site/main.py:19-20` | two separate imported extractors | branch + title |
| `intelligence.py` | no resolver — infers from title | title only |

The claim file at `docs/factory/runs/WO-NNN.json` in the Clarion repo is authoritative but nothing consults it for identity resolution. The double auto-close of PR #430 (July 22, 2026) was the direct cost: a merged PR whose title mentioned WO-410 was matched by the title-based reconciler and incorrectly completed the WO-410 dispatch entry, triggering closure of an unrelated open PR.

Additionally, the in-memory `_acted_on` dedup dict in `intelligence.py` resets on orchestrator restart, allowing the intelligence loop to repeat actions (re-close Dependabot PRs, create duplicate conflict WOs, re-clear ghost entries) after every restart.

## What to Build

### 1. `services/orchestrator/wo_resolver.py`

```python
def resolve_wo_for_pr(pr: dict) -> int | None:
    """
    Fixed precedence:
    1. branch name: wo/(\d+)- pattern
    2. PR title: WO-(\d+) as last resort
    Returns None if no WO can be identified.
    """

def extract_wo_from_branch(branch: str) -> int | None:
    m = re.match(r"wo/(\d+)-", branch)
    return int(m.group(1)) if m else None

def extract_wo_from_title(title: str) -> int | None:
    m = re.search(r"\bWO-(\d+)\b", title, re.IGNORECASE)
    return int(m.group(1)) if m else None
```

Pure functions — no side effects, fully testable.

### 2. Replace all six call sites to use `wo_resolver`

- `_fetch_open_pr_wos()`: use `resolve_wo_for_pr()` — branch first
- `_fetch_recently_merged_wo_prs()`: use `extract_wo_from_branch()` (already correct, centralize)
- `orchestrator.py:4487`: use `resolve_wo_for_pr()`
- `pr-watchdog/watchdog.py`: import shared resolver
- `status-site/main.py`: import shared resolver (drop the two separate extractors)
- `intelligence.py`: use shared resolver for all PR-to-WO mapping

No `re.search(r"WO-(\d+)")` pattern should appear outside `wo_resolver.py`.

### 3. Persist `_acted_on` dedup to disk

In `intelligence.py`, replace the in-memory dict with a persistent JSON file alongside `intelligence_last_run.json`. Load on startup, flush after each pass.

```python
_ACTED_ON_PATH = DATA_DIR / "intelligence_acted_on.json"
```

## Acceptance Criteria

- [ ] `wo_resolver.py` exists with the three functions above
- [ ] All six call sites use functions from `wo_resolver.py`
- [ ] `resolve_wo_for_pr` prefers branch over title when both present
- [ ] Unit tests: branch-wins, title-fallback, no-match, branch-only, title-only
- [ ] `_acted_on` dedup survives orchestrator restart
- [ ] No duplicate intelligence actions after restart (verified by test)

## Files

- `services/orchestrator/wo_resolver.py` — new
- `services/orchestrator/orchestrator.py` — 3 call sites updated
- `services/orchestrator/intelligence.py` — use resolver; persist `_acted_on`
- `services/pr-watchdog/watchdog.py` — use resolver
- `services/status-site/main.py` — use resolver
- `services/orchestrator/tests/test_wo_resolver.py` — new
