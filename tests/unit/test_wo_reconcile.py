"""Tests for services/status-site/wo_reconcile.py — the layer that decides
what every work-order number on the dashboard means.

Three live defects are pinned here:

* An open PR losing to a merged PR that merely named the WO in its title.
  WO-449 had PR #523 open and in review while the board filed it under Done,
  because the docs PR "Enforce Policy UX Program — WO-449–456" merged first
  and resolve_all_wos_for_pr credited every number in that title.
* Spec files silently overwriting each other. 442 files collapsed to 434 WO
  numbers via `results[spec.number] = spec`, and which file won depended on
  filesystem glob order — so a WO's status could change across restarts.
* Work orders with an open PR, a live branch or an active dispatch entry but
  no spec file being dropped from every count. WO-457 and WO-461 had agents
  running and appeared in the PR queue while contributing nothing to Total WOs.

wo_reconcile.py deliberately imports nothing beyond the standard library and
wo_parser, so it can be tested here without FastAPI (which CI does not
install) — main.py keeps the I/O and this keeps the rules.
"""

from __future__ import annotations

import sys
from pathlib import Path

STATUS_SITE_DIR = Path(__file__).resolve().parents[2] / "services" / "status-site"
sys.path.insert(0, str(STATUS_SITE_DIR))

from wo_parser import parse_wo_file  # noqa: E402
from wo_reconcile import (  # noqa: E402
    agents_in_flight,
    apply_live_status,
    build_wo_index,
    dispatch_status_counts,
)


def _board(wos: dict) -> dict[str, list[int]]:
    columns: dict[str, list[int]] = {}
    for num, spec in sorted(wos.items()):
        columns.setdefault(spec.board_column, []).append(num)
    return columns


def _spec(number: int, status: str = "📋 Open", title: str = "Some work"):
    content = f"# WO-{number} — {title}\n\n**Status:** {status}\n**Priority:** P2\n"
    return parse_wo_file(content, f"WO-{number}-some-work.md", repo="dentroio/clarion")


def _open_pr(number: int, wo_number: int, ci_state: str = "passing", title: str = ""):
    return {
        "number": number,
        "title": title or f"WO-{wo_number}: implement it",
        "wo_number": wo_number,
        "ci_state": ci_state,
    }


def _merged_pr(title: str, branch: str = "docs/something", merged_at: str = "2026-08-04T00:00:00Z"):
    return {"title": title, "head": {"ref": branch}, "merged_at": merged_at}


def _branch(wo_number: int, name: str = ""):
    return {"wo_number": wo_number, "branch": name or f"wo/{wo_number}-slug"}


# ── Open PR outranks a merged PR that merely names the WO ────────────────────


def test_open_pr_beats_merged_pr_naming_the_same_wo():
    """The WO-449 case: a merged docs PR whose title lists a range of WO
    numbers must not stamp one of them Done while its own PR is still open."""
    wos = {449: _spec(449)}

    apply_live_status(
        wos,
        branches=[],
        prs=[_open_pr(523, 449)],
        dispatch={},
        merged_prs=[_merged_pr("docs(pm): Enforce Policy UX Program — WO-449–456")],
    )

    assert wos[449].board_column == "review"
    assert wos[449].pr_number == 523


def test_merged_pr_with_no_open_pr_still_marks_done():
    wos = {449: _spec(449)}

    apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={},
        merged_prs=[_merged_pr("WO-449: Policy Vocabulary Unification")],
    )

    assert wos[449].board_column == "done"


def test_active_dispatch_still_beats_a_merged_pr():
    """Pre-existing guard (the WO-440 case) must survive the open-PR fix."""
    wos = {440: _spec(440)}

    apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={"WO-440": {"status": "in_progress", "backend": "cursor"}},
        merged_prs=[_merged_pr("WO-440: spec decision only")],
    )

    assert wos[440].board_column == "in_progress"


def test_deferred_wo_survives_a_merged_pr_that_only_names_it():
    """The WO-484 case: a human deferred it on purpose, then PR #578 — a pure
    "docs(wo): backfill work-order specs for WO-479/480/481/483, file WO-484"
    commit that implemented nothing — merged and named it in passing. A title
    mention must not silently reverse a deliberate Deferred decision."""
    wos = {484: _spec(484, status="⏸ Deferred")}

    apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={},
        merged_prs=[
            _merged_pr(
                "docs(wo): backfill work-order specs for WO-479/480/481/483, file WO-484"
            )
        ],
    )

    assert wos[484].board_column == "deferred"


def test_filing_pr_does_not_complete_an_open_wo():
    """WO-482 / WO-508: 'docs(wo): file WO-N' on a wo/N- branch is the spec
    landing, not the implementation. The board used to stamp those Done."""
    wos = {482: _spec(482, status="🔲 Open (filed 2026-08-12)")}

    apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={},
        merged_prs=[
            _merged_pr(
                "docs(wo): file WO-482 — Neo4j connect_devices() silent write loss",
                branch="wo/482-neo4j-write-loss",
            )
        ],
    )

    assert wos[482].board_column == "open"


def test_program_scope_docs_pr_does_not_complete_named_wos():
    """'docs(pm): Identity Quality Loop (WO-494–498)' scoped the work; it
    did not ship WO-495–498. Range mentions must not flip them to Done."""
    wos = {495: _spec(495, status="🔲 Open — spec written 2026-08-15")}

    apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={},
        merged_prs=[
            _merged_pr(
                "docs(pm): Identity Quality Loop (WO-494–498) and audit canvas",
                branch="docs/identity-quality-loop-wos",
            )
        ],
    )

    assert wos[495].board_column == "open"


def test_implementation_title_still_marks_done():
    wos = {488: _spec(488, status="🔲 Open (filed 2026-08-14)")}

    apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={},
        merged_prs=[
            _merged_pr(
                "WO-488: Fix AP uplink graph edge + capture AP switching mode via RESTCONF",
                branch="wo/488-ap-switching-mode-topology",
            )
        ],
    )

    assert wos[488].board_column == "done"


def test_open_pr_with_failing_ci_is_blocked_not_done():
    wos = {449: _spec(449)}

    apply_live_status(
        wos,
        branches=[],
        prs=[_open_pr(523, 449, ci_state="failing")],
        dispatch={},
        merged_prs=[_merged_pr("chore: touch WO-449 docs")],
    )

    assert wos[449].board_column == "blocked"


# ── Duplicate WO numbers resolve deterministically ───────────────────────────


def _named(filename: str, number: int, status: str):
    content = f"# WO-{number} — Title\n\n**Status:** {status}\n**Priority:** P2\n"
    return filename, parse_wo_file(content, filename, repo="dentroio/clarion")


def test_agent_brief_never_shadows_the_real_spec():
    real = _named("WO-287-connector-health.md", 287, "📋 Open")
    brief = _named("WO-287-AGENT-BRIEF.md", 287, "✅ Complete")

    for entries in ([real, brief], [brief, real]):
        index = build_wo_index(entries)
        assert index.specs[287].board_column == "open"
        assert [d.kept for d in index.duplicates] == ["WO-287-connector-health.md"]
        assert index.unresolved_duplicates == []


def test_two_real_specs_sharing_a_number_are_reported_not_hidden():
    """WO-314 in the tracked repo: two genuinely different work orders share a
    number. The dashboard can only pick one — it must pick the same one every
    time and say the collision exists."""
    a = _named("WO-314-connector-decommission.md", 314, "📋 Open")
    b = _named("WO-314-routers-missing-vendor-column.md", 314, "✅ Complete")

    first = build_wo_index([a, b])
    second = build_wo_index([b, a])

    assert first.specs[314].board_column == second.specs[314].board_column
    assert len(first.unresolved_duplicates) == 1
    dup = first.unresolved_duplicates[0]
    assert dup.number == 314
    assert dup.shadowed == ["WO-314-routers-missing-vendor-column.md"]


def test_index_keeps_every_distinct_number():
    entries = [_named(f"WO-{n}-slug.md", n, "📋 Open") for n in (10, 11, 12)]
    entries.append(_named("WO-11-AGENT-BRIEF.md", 11, "✅ Complete"))

    index = build_wo_index(entries)

    assert sorted(index.specs) == [10, 11, 12]
    assert len(index.duplicates) == 1


# ── Work orders that exist only as live activity ─────────────────────────────


def test_wo_with_an_open_pr_but_no_spec_is_surfaced():
    """WO-457/WO-461: open PR, live branch, running agent, no spec file. They
    were invisible to Total WOs and to every board column."""
    wos: dict = {}

    synthesized = apply_live_status(
        wos,
        branches=[_branch(457)],
        prs=[_open_pr(524, 457, title="WO-457: Operate page shell")],
        dispatch={},
        merged_prs=[],
        repo="dentroio/clarion",
    )

    assert synthesized == [457]
    assert wos[457].spec_missing is True
    assert wos[457].board_column == "review"
    assert wos[457].title == "Operate page shell"
    assert wos[457].repo == "dentroio/clarion"


def test_active_dispatch_without_spec_or_branch_is_surfaced():
    wos: dict = {}

    synthesized = apply_live_status(
        wos, branches=[], prs=[], dispatch={"WO-461": {"status": "in_progress"}}, merged_prs=[]
    )

    assert synthesized == [461]
    assert wos[461].board_column == "in_progress"


def test_merged_history_alone_does_not_invent_work_orders():
    """merged_wo_nums scrapes every WO-NNN across 56 days of merged titles,
    most of them passing references. Synthesizing those would fill the Done
    column with work orders that never existed here."""
    wos: dict = {}

    synthesized = apply_live_status(
        wos,
        branches=[],
        prs=[],
        dispatch={"WO-300": {"status": "complete"}},
        merged_prs=[_merged_pr("WO-1035: Resolve conflict: PR #455 — WO-417: Coverage")],
    )

    assert synthesized == []
    assert wos == {}


def test_existing_specs_are_never_replaced_by_placeholders():
    wos = {449: _spec(449, title="Real spec title")}

    synthesized = apply_live_status(
        wos, branches=[_branch(449)], prs=[_open_pr(523, 449)], dispatch={}, merged_prs=[]
    )

    assert synthesized == []
    assert wos[449].title == "Real spec title"
    assert wos[449].spec_missing is False


# ── "Running" has exactly one definition ─────────────────────────────────────
#
# The Overview said 3, the PM board said 5 and the Factory said 5, with only
# three work orders common to the two fives. Each page had its own filter over
# the same dispatch payload. These tests hold the board column and the shared
# counter to the same number so no page can drift again.


# One dispatch entry per status the orchestrator can emit, so a new status
# can't quietly land in the wrong column.
_EVERY_STATUS = {
    "WO-450": {"status": "in_progress", "backend": "cursor"},
    "WO-451": {"status": "claimed", "backend": "claude"},
    "WO-452": {"status": "awaiting_human"},
    "WO-453": {"status": "awaiting_commit"},
    "WO-454": {"status": "retry_queued"},
    "WO-455": {"status": "rejected"},
    "WO-456": {"status": "stale"},
    "WO-457": {"status": "complete"},
}


def test_running_column_equals_the_shared_dispatch_count():
    wos = {n: _spec(n) for n in range(450, 458)}

    apply_live_status(wos, branches=[], prs=[], dispatch=_EVERY_STATUS, merged_prs=[])

    # The PM board and the Overview lifecycle strip render this column; the
    # Overview stat, the Factory status bar and /api/factory/counts render the
    # helper. They are the same set, not merely the same size.
    assert _board(wos)["in_progress"] == [450, 451]
    assert dispatch_status_counts(_EVERY_STATUS)["in_progress"] == 2


def test_claimed_counts_as_running():
    """The Overview's JavaScript filtered on `in_progress` alone and dropped
    every `claimed` WO a second after the page rendered the right number."""
    assert dispatch_status_counts({"WO-1": {"status": "claimed"}})["in_progress"] == 1


def test_each_dispatch_status_lands_in_one_predictable_column():
    wos = {n: _spec(n) for n in range(450, 458)}

    apply_live_status(wos, branches=[], prs=[], dispatch=_EVERY_STATUS, merged_prs=[])
    columns = _board(wos)

    assert columns["review"] == [452, 453]      # awaiting_human, awaiting_commit
    assert columns["open"] == [457]             # complete — falls back to the spec file's status
    assert columns["blocked"] == [455]          # rejected
    assert columns["stalled"] == [454, 456]     # retry_queued and a stale claim


def test_retry_queued_is_stalled_not_open():
    """WO-440 and WO-441 sat in Open among hundreds of never-started WOs while
    the Factory page flagged them as needing attention. Nobody is working them,
    but somebody did — Open said neither."""
    wos = {440: _spec(440), 441: _spec(441)}
    dispatch = {"WO-440": {"status": "retry_queued"}, "WO-441": {"status": "retry_queued"}}

    apply_live_status(wos, branches=[_branch(440)], prs=[], dispatch=dispatch, merged_prs=[])

    assert _board(wos)["stalled"] == [440, 441]
    assert "retry" in wos[440].status.lower()


def test_retry_queued_still_never_counts_as_running():
    """The invariant the old route-to-Open comments were protecting."""
    dispatch = {"WO-440": {"status": "retry_queued"}, "WO-456": {"status": "stale"}}
    wos = {440: _spec(440), 456: _spec(456)}

    apply_live_status(wos, branches=[], prs=[], dispatch=dispatch, merged_prs=[])

    assert dispatch_status_counts(dispatch)["in_progress"] == 0
    assert _board(wos).get("in_progress", []) == []


def test_factory_buckets_name_the_board_column_they_feed():
    """The Factory page's counts must partition into the same columns the board
    uses, or "needs attention" becomes a second name for a set the board
    already calls something else."""
    counts = dispatch_status_counts(_EVERY_STATUS)

    assert counts["stalled"] == 2       # retry_queued + stale  → Stalled
    assert counts["rejected"] == 1      # rejected              → Blocked
    assert counts["stalled"] + counts["rejected"] == counts["needs_attention"]


def test_dispatch_outranks_an_open_pr_so_running_cannot_diverge():
    """A WO can be claimed and have a PR open at the same time. Whichever way
    that resolves, the board column and the dispatch count must agree — if the
    PR won, the board would show 0 running while the Factory showed 1."""
    wos = {450: _spec(450)}
    dispatch = {"WO-450": {"status": "in_progress", "backend": "cursor"}}

    apply_live_status(wos, branches=[], prs=[_open_pr(523, 450)], dispatch=dispatch, merged_prs=[])

    assert wos[450].board_column == "in_progress"
    assert len(_board(wos)["in_progress"]) == dispatch_status_counts(dispatch)["in_progress"]
    # The PR is still linked on the card — dispatch decides the column, not the
    # metadata the reviewer needs.
    assert wos[450].pr_number == 523


def test_a_failed_gate_stays_running_while_the_agent_holds_it():
    wos = {450: _spec(450)}
    dispatch = {"WO-450": {"status": "in_progress", "step": "ci gate failed, retrying"}}

    apply_live_status(wos, branches=[], prs=[], dispatch=dispatch, merged_prs=[])

    assert wos[450].board_column == "in_progress"
    assert "gate failed" in wos[450].agent_step


# ── Branch on GitHub, nobody dispatched ──────────────────────────────────────


def test_branch_without_dispatch_is_stalled_not_running():
    """WO-435 and WO-438: a pushed branch with an agent-status file on disk but
    no dispatch entry. They filled two of the five slots in the PM board's
    Running column while the Factory, reading dispatch, never listed them."""
    wos = {435: _spec(435), 438: _spec(438)}
    branches = [
        {"wo_number": 435, "branch": "wo/435-slug", "agent_status": {"agent": "cursor", "step": "wrote tests"}},
        _branch(438),
    ]

    apply_live_status(wos, branches=branches, prs=[], dispatch={}, merged_prs=[])

    assert _board(wos)["stalled"] == [435, 438]
    assert dispatch_status_counts({})["in_progress"] == 0
    assert "Stalled" in wos[435].status


def test_a_leftover_branch_does_not_drag_a_finished_wo_backwards():
    """PM View listed WO-417 as in-flight while rendering it under Done on the
    same page, because merge doesn't always delete the branch."""
    wos = {417: _spec(417, status="✅ Complete")}

    apply_live_status(wos, branches=[_branch(417)], prs=[], dispatch={}, merged_prs=[])

    assert wos[417].board_column == "done"


def test_branch_only_wo_is_dropped_from_agents_in_flight_once_done():
    wos = {417: _spec(417, status="✅ Complete"), 435: _spec(435)}
    branches = [_branch(417), _branch(435)]

    entries = agents_in_flight(branches, wos, dispatch={})

    assert [e["wo_number"] for e in entries] == [435]
    assert entries[0]["live"] is False


def test_agents_in_flight_says_which_kind_of_not_running_an_entry_is():
    """A branch under an open PR is waiting on a reviewer, not abandoned — the
    panel would otherwise brand every undispatched entry "stalled"."""
    wos = {449: _spec(449), 435: _spec(435)}
    branches = [_branch(449), _branch(435)]
    apply_live_status(wos, branches=branches, prs=[_open_pr(523, 449)], dispatch={}, merged_prs=[])

    columns = {e["wo_number"]: e["wo_column"] for e in agents_in_flight(branches, wos, dispatch={})}

    assert columns == {449: "review", 435: "stalled"}


def test_agents_in_flight_adds_dispatched_wos_with_no_pushed_branch():
    """wo_start.sh creates the branch locally and pushes it on the first
    commit, so the genuinely running work orders are the ones most likely to be
    missing from the GitHub branch list."""
    wos = {450: _spec(450)}
    dispatch = {"WO-450": {"status": "claimed", "backend": "cursor", "step": "reading spec"}}

    entries = agents_in_flight([], wos, dispatch=dispatch)

    assert [e["wo_number"] for e in entries] == [450]
    assert entries[0]["live"] is True
    assert entries[0]["agent_status"]["agent"] == "cursor"


def test_agents_in_flight_marks_dispatched_branches_live():
    wos = {450: _spec(450), 435: _spec(435)}
    branches = [_branch(450), _branch(435)]
    dispatch = {"WO-450": {"status": "in_progress"}}

    live = {e["wo_number"]: e["live"] for e in agents_in_flight(branches, wos, dispatch=dispatch)}

    assert live == {450: True, 435: False}
