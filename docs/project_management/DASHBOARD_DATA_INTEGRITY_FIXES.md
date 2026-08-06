# Dashboard Data Integrity — Diagnosis and Fix Spec

**Investigated:** 2026-08-05, against the live factory (`agentic-factory-factory-status-1`, port 8099)
**Repo under test by the dashboard:** `dentroio/clarion`
**All code paths below are in** `services/status-site/`

This document is a self-contained handoff. It records seven confirmed defects in how the
Overview (`/`), PM View (`/pm`), and Factory (`/factory`) pages compute their numbers,
with the live evidence for each and the prescribed fix. An implementer should not need
to redo the investigation.

**Status:** all seven defects are fixed on `wo/dashboard-wo-source-of-truth` (PR #194) —
see the Wave 1, 2 and 3 outcome sections at the end. Defect 6's original evidence turned
out to be a misreading; the defect beneath it was real and is recorded honestly in its
section.

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

**Fix as built:** `wo_reconcile.wo_completion_times()` maps each work order to the
earliest merge inside the window that names it, via `resolve_all_wos_for_pr`. Everything
labelled as work-order throughput counts those: the Overview stat, the PM velocity
buckets, the four-week average, and the projections underneath it. The PR count survives
under its own name — "195 PRs merged" beside the WO figure on the Overview, and
"47.2 PRs/wk" beside "22.0/wk" on the PM header, deliberately adjacent so the gap between
them is visible rather than something a future reader has to rediscover.

Resolving through `resolve_all_wos_for_pr` is what makes both directions come out right:
a work order spread over implementation, CI fix and conflict-resolution PRs counts once,
and a program PR closing several work orders credits each of them.

**Week attribution is by first merge, not last.** Follow-up PRs keep naming a WO for
weeks after the work landed; crediting the latest merge would drag finished work forward
into the current week and let a bar change on successive page loads. First-merge also
gives each work order exactly one bucket, which is what prevents double-counting across
weeks. The honest caveat, stated in the code: a WO whose real first merge predates the
window is credited to its first merge inside it, so it reads as newer than it was. That
is why "WOs Merged This Month" is 90 rather than the 92 distinct WOs *referenced* by PRs
merged in the last 30 days — two of those 92 first landed before the 30-day cutoff.

## Defect 6 — `list_merged_prs` silently truncates the window

`github_client.py:145-167` — `list_merged_prs` capped at 5 pages × 100 closed PRs ordered
by creation date, and returned a bare list.

**The original evidence was misread.** The 56-day cutoff was 2026-06-10 and the oldest PR
fetched merged 2026-06-16, but those six days are not missing data: exactly **one** PR was
merged in this repo before 2026-06-16, ever. The "10 Jun: 1" bar was correct — the factory
had not started yet.

The defect underneath it is real and was measured directly. Creation order is only a proxy
for merge order, so a PR opened before the cap's horizon and merged inside the window falls
off the end. Against the live repo the paged version returned **432 of the 439** PRs merged
in a 56-day window; the seven it dropped (#16–#22) were long-lived dependency bumps opened
early and merged weeks later. None named a work order, so WO velocity was unaffected — but
nothing in the code could have told anyone that, which is the actual problem.

**Fix as built:** `list_merged_prs` now queries `/search/issues` with
`is:pr is:merged merged:>=`, pages until it holds everything `total_count` reports, and
returns a `MergedPRWindow` carrying `complete` and `missing` alongside the PRs. Coverage is
answered by the API rather than assumed. Cost is unchanged — 5 requests for 439 results,
the same as the old 5-page cap, still behind the 1800s cache.

Search returns issue-shaped items with no `head.ref`. Measured before relying on it: over
56 days, resolving work orders from titles alone yields the same 179 distinct WOs as titles
plus branches, and not one PR had a branch naming a WO its title did not. This repo
requires "WO-NNN" in PR titles, which is why.

When the window *is* short, the PM chart says so instead of drawing it: a banner naming the
number of unretrieved PRs, amber bars, counts suffixed `+`, and empty buckets reading
"no data" rather than `0`. Incomplete buckets are excluded from the four-week average, so a
short fetch cannot masquerade as a slowdown and push every projected date out. A failed
fetch is treated the same way — previously it returned `[]` and rendered as eight dead
weeks.

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

## Wave 3 outcome (defects 5, 6) — same branch

| | Before | After |
|---|---|---|
| Overview "Merged This Month" | 195, labelled as work orders | **90 WOs**, with "195 PRs merged" beside it |
| PM velocity, 4-week average | 47.2/wk, labelled WOs/week | **22.0 WOs/wk**, with 47.2 PRs/wk beside it |
| All open WOs projected done | 2026-08-07 | **2026-08-10** |
| PRs retrieved for a 56-day window | 432 of 439, silently | **439 of 439**, with a completeness flag |

The projection moved 3 days on a 16-WO backlog. The shift is small only because the
backlog is small; the rate itself was halved, and it is the rate that feeds every
milestone date.

**A sanity check that did not come out clean.** 411 work orders are marked Done, but only
**179 distinct work orders have ever been named by a merged PR** in this repo's entire
history (440 merged PRs, first one 2026-06-16). So roughly 230 Done work orders have no
merge evidence behind them at all. The velocity figure is now an honest reading of merge
history, but merge history explains under half of what the board calls Done — either many
work orders were completed without a WO-named PR, or many spec files are marked Done
without the work having landed. That is a separate defect from these seven and is not
fixed here.

Read the projection accordingly: it is a burn-down of the 16 work orders open right now at
the observed merge rate, assuming no new ones arrive. The template says so in a tooltip.
It is not a prediction of when the project finishes.

## Still open

Nothing from this document. All seven defects are fixed on
`wo/dashboard-wo-source-of-truth` (PR #194).

Two follow-ups it surfaced, neither in scope here:

- **WO-314 is claimed by two different spec files** in `dentroio/clarion`. The dashboard
  resolves it deterministically and flags it; one of the two files needs renumbering.
- **230 Done work orders have no merged PR naming them** (see the sanity check above).
  Worth understanding before anyone treats "411 Done" as a delivery figure.

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
