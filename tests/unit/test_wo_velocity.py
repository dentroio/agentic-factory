"""Velocity means work orders, and a gap in the data has to look like a gap.

Two defects are pinned here.

The PM board's velocity chart and the Overview's "Merged This Month" stat both
counted merged pull requests and labelled the result work-order throughput.
Over 30 days this repo merged 195 PRs referencing 92 distinct work orders, and
95 of those PRs named none at all — so the headline read 195, the rate read
~47 WOs/week against a real ~21, and the milestone projections divided genuine
WO counts by the inflated rate. That is how the board came to claim every open
work order would be finished within the week.

Separately, `list_merged_prs` capped at five pages of PRs ordered by creation
date and returned a bare list. A PR opened before the cap's horizon and merged
inside the window fell off the end — measured, seven of 439 over 56 days — and
nothing downstream could tell the difference between a week with one merge and
a week whose data never arrived. Both rendered as a bar of height one.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

STATUS_SITE_DIR = Path(__file__).resolve().parents[2] / "services" / "status-site"
sys.path.insert(0, str(STATUS_SITE_DIR))

from wo_reconcile import (  # noqa: E402
    average_weekly_throughput,
    weekly_wo_throughput,
    wo_completion_times,
    wos_completed_since,
)

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


def _pr(title: str, days_ago: float, branch: str = ""):
    return {
        "title": title,
        "head": {"ref": branch},
        "merged_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# ── Counting work orders, not pull requests ──────────────────────────────────


def test_one_wo_delivered_across_several_prs_counts_once():
    """The common shape here: implementation, then a CI fix, then a conflict
    resolution, all naming WO-500. That is one work order delivered."""
    prs = [
        _pr("feat(api): WO-500 — add the endpoint", days_ago=6),
        _pr("fix(api): WO-500 — correct the guard", days_ago=4),
        _pr("chore: WO-500 — resolve conflict with main", days_ago=2),
    ]

    assert wos_completed_since(prs, _iso(30)) == [500]


def test_one_pr_closing_several_wos_credits_each_of_them():
    """The mirror case, and the reason this resolves through
    resolve_all_wos_for_pr rather than taking the first match: program PRs
    routinely land several work orders at once."""
    prs = [_pr("docs: Enforce Policy UX Program — WO-449, WO-450, WO-451", days_ago=3)]

    assert wos_completed_since(prs, _iso(30)) == [449, 450, 451]


def test_prs_naming_no_work_order_do_not_inflate_the_rate():
    """Roughly half of this repo's merged PRs are dependency bumps, release
    chores and hotfixes that reference no work order. Counting them is most of
    the 2.1x inflation."""
    prs = [
        _pr("feat: WO-500 — real work", days_ago=3),
        _pr("chore(deps): bump jsdom from 28.1.0 to 29.1.1", days_ago=3),
        _pr("chore(deps): update black requirement", days_ago=2),
        _pr("fix: correct a typo in the README", days_ago=1),
    ]

    assert wos_completed_since(prs, _iso(30)) == [500]

    buckets = weekly_wo_throughput(prs, NOW, weeks=1)
    assert buckets[-1]["count"] == 1, "work orders"
    assert buckets[-1]["pr_count"] == 4, "the PR count is kept, under its own name"


def test_a_wo_resolved_only_by_its_branch_still_counts():
    """Titles carry WO-NNN by convention here, but the branch is the fallback
    and must keep working for a PR whose title forgot."""
    prs = [_pr("fix: correct the guard", days_ago=2, branch="wo/612-guard")]

    assert wos_completed_since(prs, _iso(30)) == [612]


# ── One work order lands in exactly one week ─────────────────────────────────


def test_a_wo_with_merges_in_two_weeks_is_counted_in_one():
    """The double-counting trap. Summing distinct WOs per bucket independently
    would credit WO-500 to both weeks and overstate the total."""
    prs = [
        _pr("feat: WO-500 — implement", days_ago=13),
        _pr("fix: WO-500 — follow-up", days_ago=2),
    ]

    buckets = weekly_wo_throughput(prs, NOW, weeks=4)
    counts = [b["count"] for b in buckets]

    assert sum(counts) == 1, f"WO-500 counted {sum(counts)} times across {counts}"


def test_a_wo_is_attributed_to_its_first_merge_not_its_last():
    """Deliberate rule: the week the work landed, not the week someone last
    touched it. Attributing to the latest merge would drag finished work
    forward into the current week and make bars move on every page load."""
    prs = [
        _pr("feat: WO-500 — implement", days_ago=13),
        _pr("docs: WO-500 — add a note", days_ago=2),
    ]

    buckets = weekly_wo_throughput(prs, NOW, weeks=4)

    assert buckets[-2]["count"] == 1, "the week it landed"
    assert buckets[-1]["count"] == 0, "not the week of the follow-up"


def test_completion_time_is_the_earliest_merge():
    prs = [
        _pr("fix: WO-500 — later", days_ago=1),
        _pr("feat: WO-500 — earlier", days_ago=9),
    ]

    assert wo_completion_times(prs)[500] == _iso(9)


def test_a_pr_with_no_merge_timestamp_is_ignored():
    prs = [{"title": "feat: WO-500 — open, not merged", "head": {"ref": ""}, "merged_at": None}]

    assert wo_completion_times(prs) == {}


# ── A gap in the data must not read as a quiet week ──────────────────────────


def test_a_truncated_window_marks_buckets_incomplete_rather_than_zero():
    """The defect: a bucket that lost data rendered as a real low week. The
    oldest bar read "10 Jun: 1" and nobody could tell whether that was one
    merge or one merge that happened to survive the page cap."""
    prs = [_pr("feat: WO-500 — implement", days_ago=2)]

    buckets = weekly_wo_throughput(prs, NOW, weeks=4, window_complete=False)

    assert all(not b["complete"] for b in buckets)
    assert buckets[0]["count"] == 0, "the count is still reported"
    assert not buckets[0]["complete"], "but it is flagged as unknown, not as zero"


def test_a_complete_window_is_not_flagged():
    buckets = weekly_wo_throughput([_pr("feat: WO-500 — x", days_ago=2)], NOW, weeks=4)

    assert all(b["complete"] for b in buckets)


def test_an_incomplete_bucket_is_left_out_of_the_average():
    """A short bucket would drag the rate down and push every projected date
    out — a slowdown that never happened."""
    buckets = [
        {"count": 20, "complete": True},
        {"count": 20, "complete": True},
        {"count": 20, "complete": True},
        {"count": 2, "complete": False},
    ]

    assert average_weekly_throughput(buckets, window=4) == 20.0


def test_no_usable_buckets_yields_no_rate_rather_than_a_guess():
    buckets = [{"count": 3, "complete": False}, {"count": 1, "complete": False}]

    assert average_weekly_throughput(buckets, window=4) == 0.0


def test_the_average_is_wo_based_not_pr_based():
    """End to end on the shape that produced the live discrepancy: four weeks
    of PRs, twice as many PRs as work orders."""
    prs = []
    for week in range(4):
        days = week * 7 + 1
        prs += [
            _pr(f"feat: WO-{600 + week * 2} — a", days_ago=days),
            _pr(f"fix: WO-{600 + week * 2} — a follow-up", days_ago=days),
            _pr(f"feat: WO-{601 + week * 2} — b", days_ago=days),
            _pr("chore(deps): bump something", days_ago=days),
        ]

    buckets = weekly_wo_throughput(prs, NOW, weeks=4)

    assert average_weekly_throughput(buckets, window=4) == 2.0
    assert average_weekly_throughput(
        [{**b, "count": b["pr_count"]} for b in buckets], window=4
    ) == 4.0
