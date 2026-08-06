"""`list_merged_prs` has to cover the window, and admit it when it can't.

It used to page through closed PRs ordered by creation date, stop after five
pages, and return a bare list. Creation order is only a proxy for merge order,
so a PR opened before the cap's horizon and merged inside the window fell off
the end: measured against this repo, 432 of the 439 PRs merged in a 56-day
window came back, and the seven missing were long-lived dependency bumps
opened early and merged weeks later — exactly the shape the proxy misses.

The invisible part was worse than the gap. A short list looked identical to a
quiet fortnight, and the velocity chart drew the shortfall as real low weeks.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

STATUS_SITE_DIR = Path(__file__).resolve().parents[2] / "services" / "status-site"
sys.path.insert(0, str(STATUS_SITE_DIR))

import github_client  # noqa: E402


def _item(number: int, title: str, merged_at: str) -> dict:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/o/r/pull/{number}",
        "user": {"login": "someone"},
        "pull_request": {"merged_at": merged_at},
    }


def _fake_search(pages: list[list[dict]], total: int):
    """Stand in for the GitHub search endpoint, one list of items per page."""
    calls: list[dict] = []

    async def _get(path, params=None, ttl=None):
        calls.append(params or {})
        page = (params or {}).get("page", 1)
        items = pages[page - 1] if page <= len(pages) else []
        return {"total_count": total, "items": items}

    return _get, calls


def _run(days: int = 56):
    return asyncio.run(github_client.list_merged_prs(days=days))


# ── Normalizing a search result into the PR shape callers expect ─────────────


def test_a_search_item_becomes_the_pr_shape_the_app_reads():
    pr = github_client._search_item_to_pr(_item(7, "feat: WO-500 — x", "2026-08-01T00:00:00Z"))

    assert pr["number"] == 7
    assert pr["title"] == "feat: WO-500 — x"
    assert pr["merged_at"] == "2026-08-01T00:00:00Z"
    assert pr["head"] == {"ref": ""}, "search has no branch — present and empty, never absent"


def test_a_search_item_missing_its_merge_block_does_not_explode():
    pr = github_client._search_item_to_pr({"number": 7, "title": "x"})

    assert pr["merged_at"] == ""


# ── Covering the window ──────────────────────────────────────────────────────


def test_it_pages_until_it_has_everything_the_api_reports(monkeypatch):
    pages = [[_item(i, f"feat: WO-{i} — x", "2026-08-01T00:00:00Z") for i in range(n, n + 100)]
             for n in (0, 100, 200)]
    fake, calls = _fake_search(pages, total=300)
    monkeypatch.setattr(github_client, "_get", fake)

    window = _run()

    assert len(window.prs) == 300
    assert window.complete
    assert window.missing == 0
    assert [c["page"] for c in calls] == [1, 2, 3]


def test_it_stops_as_soon_as_the_window_is_covered(monkeypatch):
    """API budget matters here — the WO loader was deliberately cut to a
    handful of calls and this must not undo that."""
    fake, calls = _fake_search([[_item(1, "feat: WO-1 — x", "2026-08-01T00:00:00Z")]], total=1)
    monkeypatch.setattr(github_client, "_get", fake)

    _run()

    assert len(calls) == 1


def test_it_filters_the_qualifier_s_date_slop_by_timestamp(monkeypatch):
    """`merged:>=` takes a date, so the API returns a little more than the
    window; the precise cutoff is applied here."""
    fake, _ = _fake_search([[
        _item(1, "feat: WO-1 — inside", "2026-08-01T00:00:00Z"),
        _item(2, "feat: WO-2 — long before the window", "2020-01-01T00:00:00Z"),
    ]], total=2)
    monkeypatch.setattr(github_client, "_get", fake)

    window = _run()

    assert [p["number"] for p in window.prs] == [1]
    assert window.complete, "the dropped PR was outside the window, not missing from it"


def test_the_query_asks_for_merged_prs_in_the_window(monkeypatch):
    fake, calls = _fake_search([[]], total=0)
    monkeypatch.setattr(github_client, "_get", fake)

    _run()

    q = calls[0]["q"]
    assert "is:pr" in q and "is:merged" in q and "merged:>=" in q


# ── Admitting a shortfall ────────────────────────────────────────────────────


def test_a_short_fetch_is_reported_as_incomplete(monkeypatch):
    """The API says 1500 exist; search will not return past 1000. The result
    is a floor and has to be labelled as one."""
    pages = [[_item(i, f"feat: WO-{i} — x", "2026-08-01T00:00:00Z") for i in range(n, n + 100)]
             for n in range(0, 1000, 100)]
    fake, calls = _fake_search(pages, total=1500)
    monkeypatch.setattr(github_client, "_get", fake)

    window = _run()

    assert not window.complete
    assert window.missing == 500
    assert len(calls) == github_client._SEARCH_PAGE_LIMIT, "does not page forever"


def test_a_failed_call_is_unknown_not_zero_merges(monkeypatch):
    """Returning an empty list on error is what let an outage render as eight
    consecutive dead weeks."""
    async def _boom(path, params=None, ttl=None):
        raise RuntimeError("502 from GitHub")

    monkeypatch.setattr(github_client, "_get", _boom)

    window = _run()

    assert window.prs == []
    assert not window.complete, "no data is not the same as no merges"


def test_an_empty_but_successful_window_is_complete(monkeypatch):
    """A genuinely quiet window still has to be distinguishable from a broken
    one, in the other direction."""
    fake, _ = _fake_search([[]], total=0)
    monkeypatch.setattr(github_client, "_get", fake)

    window = _run()

    assert window.prs == []
    assert window.complete
