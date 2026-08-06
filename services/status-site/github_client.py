import base64
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
RUNS_PATH = os.getenv("RUNS_PATH", "docs/factory/runs")
# WO file contents change rarely — cache aggressively to avoid rate-limit exhaustion.
# With 350+ WO files each needing an individual API call, a short TTL burns thousands
# of requests per hour. 1800s matches the page refresh interval.
CACHE_TTL = int(os.getenv("GITHUB_CACHE_TTL", "1800"))

# Lighter TTL for dynamic data (PRs, branches, CI runs) — still needs to feel live.
LIVE_CACHE_TTL = int(os.getenv("GITHUB_LIVE_CACHE_TTL", "120"))

_cache: dict[str, tuple[float, Any]] = {}


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def _get(path: str, params: dict | None = None, ttl: int | None = None) -> Any:
    effective_ttl = ttl if ttl is not None else CACHE_TTL
    cache_key = f"{path}?{params}"
    if cache_key in _cache:
        ts, val = _cache[cache_key]
        if time.time() - ts < effective_ttl:
            return val

    url = f"https://api.github.com{path}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 403 and cache_key in _cache:
            # Rate limited — return stale cache rather than failing
            _, val = _cache[cache_key]
            return val
        resp.raise_for_status()
        val = resp.json()

    _cache[cache_key] = (time.time(), val)
    return val


async def get_default_branch() -> str:
    """The branch the dashboard treats as the truth for work orders — never
    assume "main", a repo is free to call it something else."""
    data = await _get(f"/repos/{GITHUB_REPO}")
    return data.get("default_branch", "main")


async def list_wo_files(ref: str | None = None) -> list[dict]:
    """Directory listing for the WO folder. Each entry carries a `sha` — the
    git blob id — which lets a caller check a local copy against the branch
    without downloading the file."""
    path = f"/repos/{GITHUB_REPO}/contents/{WO_PATH}"
    items = await _get(path, {"ref": ref} if ref else None)
    return [i for i in items if i["name"].endswith(".md") and i["name"].startswith("WO-")]


async def list_wo_files_for(repo: str, wo_path: str) -> list[dict]:
    path = f"/repos/{repo}/contents/{wo_path}"
    items = await _get(path)
    return [i for i in items if i["name"].endswith(".md") and i["name"].startswith("WO-")]


async def get_file_content(file_path: str, ref: str | None = None) -> str:
    path = f"/repos/{GITHUB_REPO}/contents/{file_path}"
    data = await _get(path, {"ref": ref} if ref else None)
    return base64.b64decode(data["content"]).decode("utf-8")


async def get_file_content_for(repo: str, file_path: str) -> str:
    path = f"/repos/{repo}/contents/{file_path}"
    data = await _get(path)
    return base64.b64decode(data["content"]).decode("utf-8")


async def list_open_prs() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/pulls"
    return await _get(path, {"state": "open", "per_page": 100}, ttl=LIVE_CACHE_TTL)


async def list_branches() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/branches"
    return await _get(path, {"per_page": 100}, ttl=LIVE_CACHE_TTL)


async def list_ci_runs() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/actions/runs"
    data = await _get(path, {"per_page": 30}, ttl=LIVE_CACHE_TTL)
    return data.get("workflow_runs", [])


async def get_branch_file(branch: str, file_path: str) -> str | None:
    path = f"/repos/{GITHUB_REPO}/contents/{file_path}"
    try:
        data = await _get(f"{path}?ref={branch}", ttl=LIVE_CACHE_TTL)
        return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        return None


async def get_pr_checks(pr_number: int) -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/pulls/{pr_number}/commits"
    try:
        commits = await _get(path, ttl=LIVE_CACHE_TTL)
        if not commits:
            return []
        sha = commits[-1]["sha"]
        checks_path = f"/repos/{GITHUB_REPO}/commits/{sha}/check-runs"
        data = await _get(checks_path, ttl=LIVE_CACHE_TTL)
        return data.get("check_runs", [])
    except Exception:
        return []


async def list_runners() -> list[dict]:
    try:
        data = await _get(f"/repos/{GITHUB_REPO}/actions/runners", ttl=LIVE_CACHE_TTL)
        return data.get("runners", [])
    except Exception:
        return []


async def list_active_runs() -> list[dict]:
    try:
        queued = await _get(f"/repos/{GITHUB_REPO}/actions/runs", {"status": "queued", "per_page": 20}, ttl=LIVE_CACHE_TTL)
        in_prog = await _get(f"/repos/{GITHUB_REPO}/actions/runs", {"status": "in_progress", "per_page": 20}, ttl=LIVE_CACHE_TTL)
        runs = queued.get("workflow_runs", []) + in_prog.get("workflow_runs", [])
        if runs:
            return sorted(runs, key=lambda r: r.get("created_at", ""))

        # This repo's CI usually finishes in well under a minute, so the
        # queued/in_progress window is rarely non-empty when someone actually
        # loads the page — the panel looks perpetually dead even when the
        # factory is working fine. Fall back to the last few completed runs,
        # tagged so the template can show them distinctly from a live queue.
        recent = await _get(f"/repos/{GITHUB_REPO}/actions/runs", {"per_page": 5}, ttl=LIVE_CACHE_TTL)
        fallback = recent.get("workflow_runs", [])
        for r in fallback:
            r["is_recent_fallback"] = True
        return fallback
    except Exception:
        return []


@dataclass(frozen=True)
class MergedPRWindow:
    """Merged PRs for a time window, plus whether we actually got all of them.

    The completeness flag is the point. A chart that draws a truncated bucket
    as a low bar is worse than one that admits it doesn't know.
    """

    prs: list[dict]
    since: str
    total_reported: int
    complete: bool

    @property
    def missing(self) -> int:
        return max(self.total_reported - len(self.prs), 0)


# The search API refuses to return past 1000 results regardless of paging.
_SEARCH_PAGE_LIMIT = 10


def _search_item_to_pr(item: dict) -> dict:
    """Normalize a search result into the PR shape the rest of the app reads.

    Search returns issue-shaped items, so there is no `head.ref`. For merged
    PRs that costs nothing measurable here: over the last 56 days, resolving
    work orders from titles alone yields the same 179 distinct WOs as
    resolving from titles plus branches, and not one PR had a branch naming a
    WO its title didn't. This repo's PR titles are required to carry
    "WO-NNN", which is why. `head` is still present and empty so callers can
    keep using resolve_all_wos_for_pr unchanged.
    """
    return {
        "number": item.get("number"),
        "title": item.get("title", "") or "",
        "merged_at": (item.get("pull_request") or {}).get("merged_at", "") or "",
        "html_url": item.get("html_url", ""),
        "user": item.get("user") or {},
        "head": {"ref": ""},
    }


async def list_merged_prs(days: int = 56) -> MergedPRWindow:
    """Every PR merged in the last `days`, via search's `merged:>=` qualifier.

    This used to page through `/pulls?state=closed&sort=created`, capped at
    five pages, and return a bare list. Two problems, one of them invisible.

    Creation order is only a proxy for merge order, so a PR opened before the
    cap's horizon and merged inside the window fell off the end. Measured
    against this repo: the paged version returned 432 of the 439 PRs merged in
    a 56-day window. The seven it dropped were long-lived dependency bumps
    opened early and merged weeks later — exactly the shape the proxy misses.

    Worse, nothing could tell. The cap produced a short list indistinguishable
    from a quiet fortnight, and the velocity chart rendered the shortfall as
    real low weeks. Search filters on merge time directly and reports
    `total_count`, so "did we get everything" is answered by the API rather
    than assumed — and when the answer is no, callers are told.
    """
    from datetime import UTC, datetime, timedelta

    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # merged:>= takes a date, so this over-selects by up to a day; the
    # timestamp filter below trims it. total_count describes the same
    # date-granular set as the items, so the two stay comparable.
    query = f"repo:{GITHUB_REPO} is:pr is:merged merged:>={since[:10]}"

    items: list[dict] = []
    total = 0
    try:
        for page in range(1, _SEARCH_PAGE_LIMIT + 1):
            data = await _get(
                "/search/issues",
                {
                    "q": query,
                    "per_page": 100,
                    "page": page,
                    "sort": "created",
                    "order": "desc",
                    "advanced_search": "true",
                },
            )
            total = data.get("total_count", 0)
            batch = data.get("items", []) or []
            items.extend(batch)
            if not batch or len(items) >= total:
                break
    except Exception:
        # No data at all is not zero merges — say so, so the chart can render
        # "unknown" instead of eight empty weeks.
        return MergedPRWindow(prs=[], since=since, total_reported=0, complete=False)

    prs = [p for p in map(_search_item_to_pr, items) if p["merged_at"] >= since]
    return MergedPRWindow(
        prs=prs,
        since=since,
        total_reported=total,
        complete=len(items) >= total,
    )
