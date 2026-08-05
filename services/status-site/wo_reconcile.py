"""Work-order indexing and live-status reconciliation.

This is the layer that decides what every number on the dashboard means:
which spec file owns a WO number, and how spec status, dispatch state, live
branches, open PRs and merged PRs combine into one board column.

It lives outside main.py on purpose. main.py owns I/O (HTTP routes, GitHub
calls, template rendering) and can only be imported with FastAPI and Jinja2
present; these rules need to be unit-testable with nothing but the standard
library, because they are the part that has repeatedly been wrong in ways no
smoke test catches — a plausible-looking number that is simply not true.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from wo_parser import WOSpec, resolve_all_wos_for_pr

# Canonical dispatch-status buckets. "Running" on every page means exactly
# IN_PROGRESS_STATUSES — the orchestrator has this WO claimed by an agent right
# now. Before this was pinned down, four call sites each defined it their own
# way and the same factory reported 5, 5 and 3 running on three pages, with
# only three work orders common to the two fives: the Overview board counted
# any WO with a GitHub branch, the Factory counted everything not complete,
# and the Overview's own JavaScript re-filtered on `in_progress` alone a second
# after load, overwriting the number the server had just rendered.
#
# Nothing may re-derive these sets — not another module, not a template, not
# the client-side JS. tests/unit/test_running_count_single_source.py fails CI
# if a call site starts computing its own.
IN_PROGRESS_STATUSES = {"claimed", "in_progress"}
AWAITING_REVIEW_STATUSES = {"awaiting_human", "awaiting_commit"}
NEEDS_ATTENTION_STATUSES = {"stale", "rejected", "retry_queued"}

# The subset of the above that means "an attempt happened and stopped, and
# nobody is on it now" — these land in the board's Stalled column. `rejected`
# is the odd one out: it needs a human, but it needs one to rework a specific
# review verdict, so it goes to Blocked.
STALLED_STATUSES = {"stale", "retry_queued"}

# An agent is attached to the work order — it is either driving it or parked on
# it waiting for a human. This is the set that earns a card in "Agents in
# Flight"; a bare branch on GitHub does not.
_AGENT_ATTACHED_STATUSES = IN_PROGRESS_STATUSES | AWAITING_REVIEW_STATUSES


def dispatch_status_counts(dispatch: dict) -> dict:
    """The one place any page gets its dispatch-derived counts.

    `tracked` is every entry the orchestrator still has open, which is a
    strictly wider thing than `in_progress` — the Factory page lists all of
    them, so it needs the number, but it must never be presented as a count of
    running work.
    """
    statuses = [w.get("status") for w in dispatch.values()]
    in_progress = sum(1 for s in statuses if s in IN_PROGRESS_STATUSES)
    awaiting_review = sum(1 for s in statuses if s in AWAITING_REVIEW_STATUSES)
    needs_attention = sum(1 for s in statuses if s in NEEDS_ATTENTION_STATUSES)
    return {
        "in_progress": in_progress,
        "awaiting_review": awaiting_review,
        "needs_attention": needs_attention,
        # needs_attention split by where the board actually puts each one, so
        # the Factory page can name its buckets after board columns instead of
        # coining a fourth word for "not running." One label per set was the
        # whole point of pinning the running definition down.
        "stalled": sum(1 for s in statuses if s in STALLED_STATUSES),
        "rejected": sum(1 for s in statuses if s == "rejected"),
        "total_active": in_progress + awaiting_review + needs_attention,
        "tracked": sum(1 for s in statuses if s != "complete"),
    }


def dispatch_by_wo_number(dispatch: dict | None) -> dict[int, dict]:
    """Dispatch keyed by WO number instead of by "WO-NNN" string id."""
    by_number: dict[int, dict] = {}
    for wo_id, entry in (dispatch or {}).items():
        try:
            by_number[int(re.sub(r"[^0-9]", "", wo_id))] = entry
        except (ValueError, TypeError):
            pass
    return by_number


# WO-NNN-AGENT-BRIEF.md files sit in the same directory as the real
# WO-NNN-*.md spec and parse to the same number. They are agent hand-off
# notes, not the work order, so they must never be the file that decides a
# WO's status.
_AGENT_BRIEF_RE = re.compile(r"-AGENT-BRIEF\.md$", re.IGNORECASE)

# Leading "WO-NNN:" / "WO-NNN —" in a PR title, stripped when a PR title is
# all we have to name a work order with.
_PR_TITLE_PREFIX_RE = re.compile(r"^\s*WO-\d+\s*[:—–-]\s*")


def _is_agent_brief(filename: str) -> bool:
    return bool(_AGENT_BRIEF_RE.search(filename))


def spec_file_rank(filename: str) -> tuple[int, str]:
    """Ordering used whenever several files claim one WO number: the real spec
    ahead of an AGENT-BRIEF companion, then alphabetical so the choice is the
    same on every machine and every restart. Anywhere that picks a file for a
    WO number has to sort by this, or the board and the WO detail page can
    quietly disagree about which file is that WO."""
    return (1 if _is_agent_brief(filename) else 0, filename)


@dataclass(frozen=True)
class WODuplicate:
    """Two or more spec files claiming the same WO number."""

    number: int
    kept: str
    shadowed: list[str]
    # True when the collision is not the known AGENT-BRIEF pattern, i.e. two
    # genuinely different work orders were given the same number. That is a
    # data problem in the tracked repo — the dashboard can only pick one
    # deterministically and say so.
    unresolved: bool


@dataclass
class WOIndex:
    specs: dict[int, WOSpec]
    duplicates: list[WODuplicate]

    @property
    def unresolved_duplicates(self) -> list[WODuplicate]:
        return [d for d in self.duplicates if d.unresolved]


def build_wo_index(entries: Iterable[tuple[str, WOSpec]]) -> WOIndex:
    """Collapse (filename, spec) pairs to one spec per WO number.

    This used to be `results[spec.number] = spec` inside the file loop, which
    meant the last file the filesystem happened to hand back won. Directory
    order is not stable across machines or restarts, so eight WO numbers in
    the live repo showed a status that depended on glob order — the same
    dashboard could report a WO as Done or Open on two consecutive boots.
    Order the candidates instead of racing them, and keep what was thrown
    away so the UI can admit the ambiguity rather than hide it.
    """
    by_number: dict[int, list[tuple[str, WOSpec]]] = defaultdict(list)
    for filename, spec in entries:
        by_number[spec.number].append((filename, spec))

    specs: dict[int, WOSpec] = {}
    duplicates: list[WODuplicate] = []
    for number, candidates in sorted(by_number.items()):
        candidates.sort(key=lambda c: spec_file_rank(c[0]))
        kept_name, kept_spec = candidates[0]
        specs[number] = kept_spec
        if len(candidates) > 1:
            shadowed = [name for name, _ in candidates[1:]]
            duplicates.append(
                WODuplicate(
                    number=number,
                    kept=kept_name,
                    shadowed=shadowed,
                    unresolved=not all(_is_agent_brief(n) for n in shadowed),
                )
            )
    return WOIndex(specs=specs, duplicates=duplicates)


def _placeholder_spec(
    number: int,
    pr: dict | None,
    branch: dict | None,
    dispatch_entry: dict | None,
    repo: str,
) -> WOSpec:
    title = ""
    if pr:
        title = _PR_TITLE_PREFIX_RE.sub("", pr.get("title", "") or "").strip()
    if not title and dispatch_entry:
        title = (dispatch_entry.get("title") or "").strip()
    if not title and branch:
        title = branch.get("branch", "")
    return WOSpec(
        number=number,
        title=title or f"WO-{number}",
        status="",
        priority="",
        effort="",
        services="",
        depends_on=[],
        program="",
        raw="",
        repo=repo,
        spec_missing=True,
    )


def apply_live_status(
    wos: dict[int, WOSpec],
    branches: list[dict],
    prs: list[dict],
    dispatch: dict | None = None,
    merged_prs: list[dict] | None = None,
    repo: str = "",
) -> list[int]:
    """Reconcile spec status against live GitHub and dispatch state, in place.

    Returns the WO numbers that had no spec file and were synthesized from
    live activity alone.
    """
    branch_wo_map = {b["wo_number"]: b for b in branches if b["wo_number"]}
    pr_wo_map: dict[int, dict] = {}
    for pr in prs:
        if pr["wo_number"]:
            pr_wo_map[pr["wo_number"]] = pr

    # Build set of WO numbers with merged PRs — authoritative "done" signal.
    # Use resolve_all_wos_for_pr, not resolve_wo_for_pr: conflict-resolution/
    # follow-up PRs routinely mention two WOs in one title (e.g. "WO-1035:
    # Resolve conflict: PR #455 — WO-417: ..."), and both are genuinely done
    # by that merge — crediting only the first left the second stuck looking
    # unfinished indefinitely.
    merged_wo_nums: set[int] = set()
    for p in (merged_prs or []):
        merged_wo_nums.update(resolve_all_wos_for_pr(p))

    # Dispatch keyed by WO number, so we can mark active WOs even when the
    # branch hasn't been pushed to GitHub yet (which is the normal case during
    # agent work — branches are local-only until the PR is created).
    dispatch_map = dispatch_by_wo_number(dispatch)

    # Work orders that exist only as live activity — an open PR, a branch on
    # GitHub, or a dispatch entry that isn't complete — with no spec file to
    # key them off. WO-457 and WO-461 were in exactly that state: open PRs,
    # pushed branches, agents running, and yet absent from Total WOs and from
    # every board column, so the PR queue and the board on the same page
    # disagreed about how much work was in flight. Give them a placeholder and
    # let the loop below status them like any other WO.
    #
    # Merged PRs are deliberately not a trigger here. merged_wo_nums scrapes
    # every WO-NNN mentioned across 56 days of merged titles, most of them
    # passing references to long-finished or other-repo work; synthesizing
    # those would bury the Done column in numbers that never existed.
    live_nums = set(pr_wo_map) | set(branch_wo_map)
    live_nums |= {n for n, e in dispatch_map.items() if e.get("status") not in (None, "complete")}
    synthesized: list[int] = []
    for num in sorted(live_nums - set(wos)):
        wos[num] = _placeholder_spec(
            num, pr_wo_map.get(num), branch_wo_map.get(num), dispatch_map.get(num), repo
        )
        synthesized.append(num)

    for num, spec in wos.items():
        # Dispatch state (when present) is the freshest, most specific signal for
        # a WO actively being worked right now — a live "in_progress"/"claimed"/
        # "retry_queued"/etc entry means the orchestrator has current, authoritative
        # knowledge that this WO is NOT finished, regardless of what a merged PR
        # title or a leftover branch might suggest.
        dispatch_entry = dispatch_map.get(num)
        dispatch_status = (dispatch_entry or {}).get("status") or ""
        dispatch_says_active = dispatch_entry is not None and dispatch_status != "complete"
        pr = pr_wo_map.get(num)
        branch = branch_wo_map.get(num)
        spec_column = spec.board_column

        # PR identity is metadata, not a verdict — attach it whatever the WO's
        # status turns out to be, so a card that ends up in Running still links
        # the PR the agent is pushing to.
        if pr:
            spec.pr_number = pr["number"]
            spec.ci_state = pr["ci_state"]

        # Merged PRs are normally the strongest signal — but a PR whose title
        # merely REFERENCES a WO (not its actual implementation — e.g. a
        # docs-only prerequisite/spec-decision commit) can get merged while the
        # real implementation is still in progress under dispatch tracking.
        # WO-440 hit this exactly: PR #520 was a spec-decision-only commit
        # titled "WO-440: ..." that got merged while an agent was still
        # actively implementing the WO, permanently stamping it "done" on
        # every dashboard page. Don't trust the merged-PR heuristic over a
        # dispatch entry that explicitly says otherwise.
        #
        # An open PR is the same argument one step further: it is the current
        # state of the work, while a merged title match is history. WO-449 had
        # PR #523 open and in review, and still filed under Done, because the
        # docs PR "Enforce Policy UX Program — WO-449–456" merged first and
        # named it. A WO cannot be finished and awaiting review at once; the
        # open PR wins, and it must be checked before this shortcut, not after
        # the `continue` that skips it.
        if num in merged_wo_nums and not dispatch_says_active and not pr:
            spec.status = "✅ Done"
            spec.merged_at = next(
                (p.get("merged_at", "") for p in (merged_prs or [])
                 if re.search(rf"WO-{num}\b", p.get("title", ""))),
                "",
            )
            continue

        # Dispatch state decides the column from here down, and it is checked
        # before the PR and branch cases rather than after. That ordering is
        # what makes the board's Running column and dispatch_status_counts()
        # the same number by construction: if the orchestrator says an agent
        # holds this WO, the board says Running, full stop. Deriving Running
        # from "has a GitHub branch" instead is what put WO-435 and WO-438 in
        # the PM board's Running column while the Factory page — reading the
        # same dispatch data — did not list them at all.
        if dispatch_status in IN_PROGRESS_STATUSES:
            step = dispatch_entry.get("step", "") or ""
            spec.status = "🔄 In Progress"
            # Prefer the backend field (actual AI, e.g. "cursor") over the
            # runner identity (e.g. "claude-runner") for display purposes.
            spec.agent_name = dispatch_entry.get("backend") or dispatch_entry.get("agent", "")
            # A failed gate used to move the WO to Blocked. It is still claimed
            # by an agent that is presumably fixing it, so calling it Blocked
            # made Running disagree with dispatch for exactly the WOs a human
            # most wants to see. Keep it Running and put the reason on the card.
            spec.agent_step = step
        elif dispatch_status in AWAITING_REVIEW_STATUSES:
            spec.status = "⏳ Awaiting Review"
            spec.agent_name = dispatch_entry.get("backend") or dispatch_entry.get("agent", "")
        elif dispatch_status == "rejected":
            spec.status = "🔴 Rejected — awaiting rework"
        elif dispatch_status in STALLED_STATUSES:
            # An attempt ran and stopped, and nobody holds the WO now.
            # retry_queued used to be forced into Open by three separate
            # branches of this function, each commented as keeping it out of
            # Running — the right instinct when Open was the only alternative,
            # but it also erased the fact that the work had been tried, hiding
            # the WOs the Factory page was flagging as needing attention inside
            # a backlog of hundreds. Stalled is the home those comments wanted.
            # The invariant they protected still holds: neither status is in
            # IN_PROGRESS_STATUSES, so neither can be counted as running.
            spec.status = (
                "⚠️ Stalled — attempt failed, queued for retry"
                if dispatch_status == "retry_queued"
                else "⚠️ Stalled — claim went stale, no agent on it"
            )
        elif pr:
            # No live dispatch, but a PR is open: the work is with a reviewer.
            if pr["ci_state"] == "failing":
                spec.status = "🔴 Blocked (CI failing)"
            elif pr["ci_state"] == "pending":
                spec.status = "👀 In Review (CI running)"
            else:
                spec.status = "👀 In Review (ready)"
        elif branch and spec_column not in ("done", "deferred"):
            # A branch on GitHub, no PR, and nobody dispatched. Work started and
            # then stopped. This is not Running (no agent) and not Open (it was
            # started, and there is a branch to clean up or resume), so it gets
            # its own column rather than being rounded to whichever neighbour is
            # convenient. The done/deferred guard matters: a leftover branch on
            # a finished WO used to drag it back out of Done, which is how PM
            # View listed WO-417 as in-flight and Done on the same screen.
            spec.status = "⚠️ Stalled — branch pushed, no agent on it"
            agent_status = branch.get("agent_status") or {}
            spec.agent_name = agent_status.get("agent", "")
            spec.agent_step = agent_status.get("step", "")

    return synthesized


def wo_completion_times(merged_prs: Iterable[dict]) -> dict[int, str]:
    """Work order number -> when the work landed, from merged PR titles.

    Velocity is a count of work orders, not of pull requests, and the two are
    nowhere near each other: over 30 days this repo merged 195 PRs referencing
    92 distinct work orders, and 95 of those PRs named no work order at all.
    Counting PRs and labelling the result "WOs/week" inflated the rate ~2.1x,
    and the milestone projections then divided real WO counts by that inflated
    rate — which is how the board concluded every open work order would be
    finished within the week.

    Resolving through resolve_all_wos_for_pr is what makes both directions
    come out right: a work order split across several PRs is one entry here,
    and one PR closing several work orders credits each of them.

    A work order lands in the week of its **earliest** merge inside the
    window, not its latest. Follow-up PRs — conflict resolutions, doc fixes,
    revert-and-reland — keep naming a WO for weeks after the work is done, and
    attributing it to the last of those would drag finished work forward into
    the current week and let a WO hop between buckets on successive page
    loads. Earliest also gives each work order exactly one bucket, which is
    what stops it being counted twice across weeks.

    The window edge is the honest caveat: a WO whose real first merge predates
    the window is credited to its first merge inside it, so it reads as newer
    than it was.
    """
    first_seen: dict[int, str] = {}
    for pr in merged_prs:
        merged_at = pr.get("merged_at") or ""
        if not merged_at:
            continue
        for num in resolve_all_wos_for_pr(pr):
            if num not in first_seen or merged_at < first_seen[num]:
                first_seen[num] = merged_at
    return first_seen


def wos_completed_since(merged_prs: Iterable[dict], since: str) -> list[int]:
    """Distinct work orders whose first in-window merge is at or after `since`."""
    return sorted(n for n, at in wo_completion_times(merged_prs).items() if at >= since)


def weekly_wo_throughput(
    merged_prs: Iterable[dict],
    now,
    weeks: int = 8,
    window_complete: bool = True,
) -> list[dict]:
    """Per-week buckets of work orders completed, oldest first.

    Each bucket carries `complete` so the chart can tell "one work order
    landed that week" apart from "we could not retrieve that week". They used
    to render identically — a bar of height one — which is how a short fetch
    reads as a real quiet week.

    When the fetch is short, every bucket is marked incomplete rather than
    guessing which lost data: search returns results in creation order, so a
    PR that didn't come back could have merged at any point in the window.
    """
    from datetime import timedelta

    prs = list(merged_prs)
    completion = wo_completion_times(prs)

    buckets: list[dict] = []
    for i in range(weeks - 1, -1, -1):
        start = now - timedelta(weeks=i + 1)
        end = now - timedelta(weeks=i)
        start_iso, end_iso = start.isoformat(), end.isoformat()
        wo_count = sum(1 for at in completion.values() if start_iso <= at <= end_iso)
        pr_count = sum(
            1 for p in prs if p.get("merged_at") and start_iso <= p["merged_at"] <= end_iso
        )
        buckets.append({
            "label": start.strftime("%-d %b"),
            "count": wo_count,
            "pr_count": pr_count,
            "complete": window_complete,
            "bar": "█" * wo_count if wo_count else "·",
        })
    return buckets


def average_weekly_throughput(buckets: list[dict], window: int = 4) -> float:
    """Mean work orders per week over the most recent `window` complete buckets.

    Incomplete buckets are dropped rather than averaged in. A bucket that is
    short because the fetch was short would pull the rate down and push every
    projected date out — a slowdown that never happened.
    """
    usable = [b["count"] for b in buckets[-window:] if b.get("complete", True)]
    return sum(usable) / len(usable) if usable else 0.0


def agents_in_flight(
    branches: list[dict],
    wos: dict[int, WOSpec],
    dispatch: dict | None = None,
    format_age: Callable[[str], str] | None = None,
) -> list[dict]:
    """The list of work an agent is attached to, for both pages' agent panels.

    Overview built this inline and PM View used a one-liner over raw branches,
    so the two pages contradicted each other: PM showed WO-417 as in-flight
    while rendering it under Done a few hundred pixels away, and omitted the
    three work orders that were genuinely running because wo_start.sh creates
    the branch locally and only pushes it on the agent's first commit.

    Two corrections, both of which either page alone used to get wrong:
    branches whose WO has since finished are dropped, and WOs that are
    dispatched but have no branch on GitHub yet are synthesized in. Entries
    carry `live` so the template can distinguish an agent that is working right
    now from a branch nobody is driving.
    """
    dispatch_map = dispatch_by_wo_number(dispatch)

    def _column(num) -> str:
        return wos[num].board_column if num in wos else ""

    # `wo_column` rides along so the panel can name why an entry is here
    # without a second lookup, and without calling everything undispatched
    # "stalled" — a branch sitting under an open PR is waiting on a reviewer.
    entries = [
        {
            **b,
            "live": dispatch_map.get(b.get("wo_number"), {}).get("status") in _AGENT_ATTACHED_STATUSES,
            "wo_column": _column(b.get("wo_number")),
        }
        for b in branches
        if _column(b.get("wo_number")) not in ("done", "deferred")
    ]

    covered = {b.get("wo_number") for b in entries if b.get("wo_number")}
    for num, entry in sorted(dispatch_map.items()):
        if num in covered or entry.get("status") not in _AGENT_ATTACHED_STATUSES:
            continue
        claimed_at = entry.get("claimed_at") or entry.get("last_seen") or ""
        entries.append(
            {
                "branch": entry.get("slug") or f"WO-{num}",
                "wo_number": num,
                "last_commit_sha": "",
                "last_commit_date": claimed_at,
                "last_commit_ago": (
                    format_age(claimed_at) if claimed_at and format_age else "just now"
                ),
                "agent_status": {
                    "agent": entry.get("backend") or entry.get("agent", ""),
                    "step": entry.get("step") or entry.get("status", "working"),
                },
                "live": True,
                "wo_column": _column(num),
            }
        )

    entries.sort(key=lambda e: e.get("last_commit_date") or "", reverse=True)
    return entries
