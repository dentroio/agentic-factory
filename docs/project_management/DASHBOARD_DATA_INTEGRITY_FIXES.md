# Dashboard Data Integrity — Diagnosis and Fix Spec

**Investigated:** 2026-08-05, against the live factory (`agentic-factory-factory-status-1`, port 8099)
**Repo under test by the dashboard:** `dentroio/clarion`
**All code paths below are in** `services/status-site/`

This document is a self-contained handoff. It records seven confirmed defects in how the
Overview (`/`), PM View (`/pm`), and Factory (`/factory`) pages compute their numbers,
with the live evidence for each and the prescribed fix. An implementer should not need
to redo the investigation.

**Status:** defects 1, 2, 3, 4 and 7 are fixed on `wo/dashboard-wo-source-of-truth` — see
the Wave 1 and Wave 2 outcome sections at the end. **Defects 5 and 6 remain open** and are
knowingly out of scope for that branch.

---

## Observed contradiction (live, 2026-08-05 18:06 UTC)

| Metric | Overview | PM View | Factory |
|---|---|---|---|
| Total WOs | 434 | 434 | — |
| Running | 5 on load, 3 after 15s | 5 | 3 running |
| "Active" | 5 | 13 "open WOs" | 5 active |
| In Review | 0 | 0 | — |
| Open PRs | 3 | — | — |

Ground truth at that moment: dispatch had 94 entries (89 `complete`, 3 `in_progress`,
2 `retry_queued`). Three PRs were open: #523 (WO-449), #524 (WO-457), #528 (WO-461).

---

## Defect 1 — Two sources of truth that disagree (root cause; fix first)

WO specs are read from a **local mounted checkout**; PRs, branches, CI, and merged
history come from the **live GitHub API**. The two are not the same tree.

- `main.py:43` — `LOCAL_REPO_MOUNT`, resolved by `_load_wos_from_disk()` at `main.py:148-176`
- Container mount: `/Users/stevengerhart/workspace/github/sgerhart/clarion` → `/repos/primary`
- That checkout was on branch `docs/enforce-policy-ux-program`, **not `main`**

Evidence:
- Working tree: **442** WO files. `origin/main`: **445**. Three work orders that exist on
  main (WO-458/459/460, all Complete) were invisible to every count on every page.
  > Correction (Wave 1): this originally read "477 on main, ~35 invisible". That 477 came
  > from an unanchored `rg 'WO-.*\.md'` that also matched 32 `ARCH-WO-*.md` files. The
  > defect was real; its magnitude was 3 files, not 35.
- **WO-457 and WO-461 have no spec file on that branch or on main.** They have open PRs,
  live branches, and running agents, but contribute nothing to Total WOs or any board
  column. They appear only in branch-derived "Active Agents" and the PR queue — which is
  why the pages look internally inconsistent.
- `_WOS_CACHE_TTL` (default 300s, `main.py:53`) layers staleness on top, so the WO side
  can lag the GitHub side arbitrarily.

**Fix:** give the dashboard one source of truth for work orders. Either read WO specs
from the GitHub API on the default branch (consistent with every other data source), or
pin the local mount read to `origin/main` rather than whatever branch is checked out.
If the local mount is kept for speed, it must resolve the tracked default branch
explicitly and surface a visible warning when the checkout is not on it. Also surface
WOs that have PRs/branches/dispatch but no spec file, instead of dropping them silently.

## Defect 2 — A merged PR outranks an open PR, so "In Review" reads 0

`_apply_live_status()` applies the merged-PR shortcut before the open-PR check, then
`continue`s past it:

- `main.py:421-428`

Evidence: WO-449 has open PR #523 right now, but the board files it under **Done**.
Merged PR #522 was titled `docs(pm): Enforce Policy UX Program — WO-449–456`;
`resolve_all_wos_for_pr` returns `[449]` for that title, so a docs-only PR permanently
stamped WO-449 done. The existing guard `not dispatch_says_active` only rescues WOs with
a live dispatch entry — WO-450/451/456 survived because they are actively dispatched;
WO-449 had no dispatch entry and did not.

**Fix:** an open PR is a stronger, more current signal than a merged PR title match.
Check `pr_wo_map` before `merged_wo_nums`, or add `num not in pr_wo_map` to the
merged-PR condition. Regression test: a WO with both a merged PR referencing it and a
currently-open PR must land in `review`, not `done`.

## Defect 3 — "Running" is computed four different ways

`_dispatch_status_counts()` (`main.py:66-75`) is the canonical helper and its docstring
records that this exact bug was fixed once already. Three of four call sites bypass it:

1. Overview server-side: `main.py:572` — `len(columns["in_progress"])` → **5**
2. Overview client-side: `templates/dashboard.html:332-334` — filters `status === 'in_progress'`
   only, excluding `claimed` → **3**, and it overwrites the server value on load
3. PM View: `main.py:772` — board column → **5**
4. Factory: `_dispatch_status_counts` → **3 running**, plus "5 active" meaning
   `3 running + 0 awaiting + 2 needs attention`

So Overview renders 5 and flips to 3 within milliseconds while PM shows 5 for the same
label. Factory's "5 active" coincidentally equals Overview's 5 but means something
different, which disguises the disagreement. Concretely: WO-435 and WO-438 have GitHub
branches so the board calls them Running, but have no active dispatch entry, so Factory
omits them.

Overview also blends sources inside one card: `dashboard.html:101-108` puts the
board-derived "Running Now" next to the dispatch-derived "N need attention".

**Decision (human, 2026-08-05):** "Running" means **dispatched right now — dispatch status
`claimed` or `in_progress`**. This matches the hint already printed on the PM board. Every
call site, including the JS, must route through the one shared helper. Consequence: WOs
with a branch but no live dispatch entry (WO-435, WO-438) leave the Running column and
need a deliberate, legible home. Factory's aggregate (`running + awaiting + needs
attention`) may stay but must be labeled so it cannot be read as a running count — two
pages both showing "5" for different sets is what triggered this report.

**Fix as built:** `dispatch_status_counts()` moved to `wo_reconcile.py` and is now the only
definition; `main.py` keeps no status sets of its own. Both `dispatch_running` assignments
read `["in_progress"]` from it, and the JS on the Overview and the Factory fetches the new
`GET /api/factory/counts` endpoint instead of filtering the raw dispatch payload.

The board agrees by construction rather than by coincidence: `apply_live_status()` now
checks dispatch status **before** the PR and branch cases, so if the orchestrator says an
agent holds a WO, the board's Running column says so too. One deliberate consequence — a
claimed WO whose step reads "gate failed" stays in Running with the reason on the card
instead of jumping to Blocked, because it is still held by an agent.

WO-435 and WO-438 got the deliberate home the decision above called for: a new **Stalled**
column, added to the PM board *and* the Overview lifecycle strip so the two strips remain
identical. Factory's aggregate was relabeled — the panel is "Dispatch Queue" reading
"N running / M tracked", and the status bar leads with the shared running number.

## Defect 4 — Eight WO numbers silently collapse

`main.py:172-175` — `results[spec.number] = spec` lets the last file win.

Evidence: 442 files parse successfully (zero parse failures) but yield only **434**
unique numbers. Collisions:

- `WO-287/289/291/292/293/294/295-AGENT-BRIEF.md` shadow their real specs
- `WO-314-connector-decommission.md` vs `WO-314-routers-missing-vendor-column.md` — two
  genuinely different work orders sharing a number

`Path.glob` order is filesystem-dependent, so the status shown for these WOs can change
between restarts.

**Fix:** detect collisions and prefer the real spec over an `-AGENT-BRIEF` variant
deterministically; log or surface the duplicate rather than dropping it. The genuine
WO-314 conflict is a data problem in `dentroio/clarion` and needs one of the two files
renumbered.

## Defect 5 — Velocity counts PRs but is labeled WOs

`main.py:804-807` (PM velocity) and the Overview "Merged This Month" stat both count
merged pull requests, then the result is presented as work-order throughput.

Evidence over the last 30 days: **197 merged PRs but only 92 distinct WOs**, and **97 of
those PRs reference no WO at all**. The headline 196 and the 47.0 WOs/week average are
inflated roughly 2.1×. Milestone projections (`main.py:834-841`) divide real WO counts by
that PR-based rate, producing "All 13 open WOs projected done 2026-08-07."

**Fix:** count distinct WO numbers resolved via `resolve_all_wos_for_pr`, not PRs, for
anything labeled as WO velocity or WO throughput. Keep a PR-count stat if useful, but
label it "PRs merged". Milestone projection must use the WO-based rate.

## Defect 6 — Velocity's oldest bucket is a pagination artifact

`github_client.py:145-167` — `list_merged_prs` caps at 5 pages × 100.

Evidence: for a 56-day window the cutoff was 2026-06-10, but the oldest PR actually
fetched merged 2026-06-16 — six days of the window were never retrieved. This is why the
first bar reads "10 Jun: 1"; it looks like a near-dead week and is not.

**Fix:** paginate until the window is genuinely covered (or use the search API with a
`merged:>=` qualifier), and if the cap is hit, mark the truncated buckets as incomplete
instead of rendering them as zero.

## Defect 7 — The two "agents in flight" lists disagree

Overview filters out branches whose WO is already done (`main.py:554-557`) and adds
dispatch-only WOs (`main.py:577+`). PM View does neither:

- `main.py:881` — `active_agents = [b for b in branches if b.get("agent_status")]`

Evidence: PM listed WO-417 as in-flight while showing it in Done on the same page, and
omitted WO-450/451/456 — the three genuinely running — because their branches were not
yet pushed to GitHub.

**Fix as built:** `wo_reconcile.agents_in_flight()` is the shared helper, called by both
pages. It drops branches whose WO is done or deferred, synthesizes entries for dispatched
WOs whose branch is not yet pushed, and tags each entry with `live` (a dispatch entry has
it) plus `wo_column` (where the board put it). The panels render identical lists; the
pulsing "live agent" indicator is now reserved for entries with a real dispatch entry, and
an undispatched entry is labeled by its actual column — "in review" for a branch under an
open PR, "stalled" for an abandoned one — rather than all being called stalled.

---

## Suggested sequencing

Defects 1, 2, and 4 all live in the WO-loading and status-reconciliation layer and would
conflict if worked in parallel — do them together, first, since they change what every
page reports. Defects 3 and 7 are the shared-definition cleanup and touch overlapping
code in `main.py` plus templates. Defects 5 and 6 are contained to the velocity block and
`github_client.py` and can proceed independently.

Risk tier: these change the semantics of the primary dashboard, so treat as P1 —
human merge, no auto-merge. Run `make ci-local` before any PR.

## Wave 1 outcome (defects 1, 2, 4) — implemented on `wo/dashboard-wo-source-of-truth`

Total WOs 434 → 439, In Review 0 → 3, Done 409 → 411. WO specs now come from the GitHub
API pinned to the default branch, with the local mount demoted to a blob-id-verified
content cache. Reconciliation rules were extracted to `services/status-site/wo_reconcile.py`
so they are importable in tests without `main.py`'s runtime deps.

Two findings that change assumptions for later waves:

- The local mount's `origin` is `dentroio/clarion` — **not** a fork. Only the containing
  directory path (`sgerhart/`) was misleading.
- `refs/remotes/origin/main` in that checkout **intermittently vanishes**; `git rev-parse
  origin/main` failed ten consecutive times and later recovered, and the orchestrator logs
  `[orchestrator] git pull error:` against the same mount. Do not build any dashboard
  behaviour on local git refs being reliably present.

Open data problems, not fixable in this repo's code:

- **WO-314** is two unrelated work orders sharing one number (`connector-decommission`
  and `routers-missing-vendor-column`). One needs renumbering in `dentroio/clarion`.
- **32 `ARCH-WO-*.md` files** are excluded from every count by the `WO-*.md` glob,
  presumably deliberate (`ARCH-WO-001` would collide with `WO-1`), but nothing in the UI
  acknowledges they exist. Needs a product decision.

## Wave 2 outcome (defects 3, 7) — same branch

"Running" is now one number on all three pages: **3**, meaning dispatch status `claimed`
or `in_progress`. Overview's stat and lifecycle strip, PM's header and board column, and
the Factory status bar all resolve to `dispatch_status_counts(dispatch)["in_progress"]`.

Board state after the change, identical on the Overview lifecycle strip and the PM board:

| Open | Running | In Review | Stalled | Blocked | Deferred | Done | Total |
|---|---|---|---|---|---|---|---|
| 6 | 3 | 3 | 4 | 0 | 12 | 411 | 439 |

**The Stalled column** holds work that was started and then dropped: a `retry_queued` or
`stale` dispatch claim, or a pushed branch with no dispatch entry at all. It replaces two
older behaviours that were each wrong in a different direction — a leftover branch used to
read as Running, and `retry_queued` was forced into Open by three separate branches of
`apply_live_status()`, each commented as keeping it out of Running. That instinct was
correct; Open was simply the only alternative at the time. Those comments are now
consolidated into one that explains the real reasoning, and the invariant they protected
still holds because neither status is in `IN_PROGRESS_STATUSES`.

Live membership: WO-435 and WO-438 (branch, no dispatch) and WO-440 and WO-441
(`retry_queued`).

**Factory's buckets are named after the board columns they feed** rather than a private
vocabulary for that page — "N running · N in review · N stalled · N rejected · N tracked
by dispatch". The former "N need attention" spanned two board columns (`retry_queued` and
`stale` → Stalled, `rejected` → Blocked), which is how one set ends up with two names. The
Factory's "stalled" is the dispatch-only subset of the board's Stalled column and can be
lower than it; the tooltip says so. Today: Factory 2, board 4.

**Guardrails.** `tests/unit/test_wo_reconcile.py` asserts the board's Running column and
the shared counter are the same set across every dispatch status, and covers the
branch-only, `retry_queued`, leftover-branch-on-done, and dispatch-vs-open-PR cases.
`tests/unit/test_running_count_single_source.py` is a static source check in the style of
`test_cached_get_call_sites.py`: it fails CI if `main.py` regrows its own status sets, if a
`dispatch_running` assignment stops going through the helper, or if any template filters
the dispatch payload for a running status.

## Still open

**Defects 5 and 6 are not fixed** and were deliberately excluded from
`wo/dashboard-wo-source-of-truth` to keep it reviewable. "Merged This Month" is still
counting PRs while labeled as work-order throughput, and `list_merged_prs` still truncates
the oldest bucket of the velocity window. Both remain as described above.

## How to reproduce the measurements

```bash
# rendered numbers per page
for p in "" factory pm; do curl -s "http://localhost:8099/$p" -o "/tmp/page-${p:-overview}.html"; done

# raw dispatch distribution
curl -s http://localhost:8099/api/factory/dispatch | python3 -c "
import json,sys,collections
d=json.load(sys.stdin); print(len(d), collections.Counter(v.get('status') for v in d.values()))"

# WO file inventory vs unique numbers, inside the container
docker exec agentic-factory-factory-status-1 python3 -c "
import sys; sys.path.insert(0,'/app')
from pathlib import Path
from wo_parser import parse_wo_file
files=sorted(Path('/repos/primary/docs/project_management/work_orders').glob('WO-*.md'))
specs=[parse_wo_file(p.read_text(encoding='utf-8'), p.name, repo='dentroio/clarion') for p in files]
print('files', len(files), 'unique', len({s.number for s in specs if s}))"

# worktree vs main WO counts
cd /Users/stevengerhart/workspace/github/sgerhart/clarion
git rev-parse --abbrev-ref HEAD
git ls-tree -r --name-only origin/main -- docs/project_management/work_orders/ | grep -c 'WO-.*\.md'
```
