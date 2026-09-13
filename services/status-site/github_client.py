"""GitHub REST client for the factory status dashboard.

Designed to stay under secondary rate limits: long TTLs for WO content,
a process-wide circuit breaker on 403 rate-limit responses, and stale-cache
fallbacks so a refresh never storms the API after a limit trip.
"""
from __future__ import annotations

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
CACHE_TTL = int(os.getenv("GITHUB_CACHE_TTL", "1800"))
# Live data (PRs, branches, CI). Keep modest; board no longer fans out per-PR checks.
LIVE_CACHE_TTL = int(os.getenv("GITHUB_LIVE_CACHE_TTL", "300"))
# After a rate-limit 403, pause outbound GitHub calls (seconds).
RATE_LIMIT_COOLDOWN = int(os.getenv("GITHUB_RATE_LIMIT_COOLDOWN", "300"))

_cache: dict[str, tuple[float, Any]] = {}
_rate_limited_until: float = 0.0


class GitHubRateLimited(Exception):
    """GitHub refused the request for rate limiting; caller should use mount/stale data."""


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _cache_key(path: str, params: dict | None) -> str:
    if not params:
        return path
    items = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{path}?{items}"


def _looks_like_rate_limit(resp: httpx.Response) -> bool:
    if resp.status_code != 403:
        return False
    body = (resp.text or "").lower()
    if "rate limit" in body or "secondary rate limit" in body:
        return True
    remaining = resp.headers.get("x-ratelimit-remaining")
    return remaining == "0"


def _trip_rate_limit(resp: httpx.Response | None = None) -> None:
    global _rate_limited_until
    reset_at = None
    if resp is not None:
        raw = resp.headers.get("x-ratelimit-reset")
        if raw and raw.isdigit():
            reset_at = float(raw)
        retry = resp.headers.get("retry-after")
        if retry and retry.isdigit():
            reset_at = max(reset_at or 0.0, time.time() + int(retry))
    until = reset_at if reset_at and reset_at > time.time() else time.time() + RATE_LIMIT_COOLDOWN
    _rate_limited_until = max(_rate_limited_until, until)


def rate_limit_active() -> bool:
    return time.time() < _rate_limited_until


def rate_limit_remaining_seconds() -> int:
    return max(0, int(_rate_limited_until - time.time()))


def clear_rate_limit_for_tests() -> None:
    global _rate_limited_until
    _rate_limited_until = 0.0
    _cache.clear()


def _stale(cache_key: str) -> Any | None:
    hit = _cache.get(cache_key)
    return hit[1] if hit else None


async def _get(path: str, params: dict | None = None, ttl: int | None = None) -> Any:
    effective_ttl = ttl if ttl is not None else CACHE_TTL
    cache_key = _cache_key(path, params)
    now = time.time()

    if cache_key in _cache:
        ts, val = _cache[cache_key]
        if now - ts < effective_ttl:
            return val

    if rate_limit_active():
        stale = _stale(cache_key)
        if stale is not None:
            return stale
        raise GitHubRateLimited(
            f"GitHub API rate-limited — cooling down {rate_limit_remaining_seconds()}s"
        )

    url = f"https://api.github.com{path}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if _looks_like_rate_limit(resp):
            _trip_rate_limit(resp)
            stale = _stale(cache_key)
            if stale is not None:
                return stale
            raise GitHubRateLimited(
                f"GitHub API rate limit exceeded (cooldown {RATE_LIMIT_COOLDOWN}s)"
            )
        if resp.status_code == 403 and cache_key in _cache:
            # Other 403s (SSO, permissions) — still prefer stale over hard fail.
            return _cache[cache_key][1]
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
        data = await _get(path, {"ref": branch}, ttl=LIVE_CACHE_TTL)
        return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        return None


async def get_pr_checks(pr_number: int) -> list[dict]:
    """Per-PR check runs — expensive (2 API calls). Prefer board paths that skip this."""
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
        queued = await _get(
            f"/repos/{GITHUB_REPO}/actions/runs",
            {"status": "queued", "per_page": 20},
            ttl=LIVE_CACHE_TTL,
        )
        in_prog = await _get(
            f"/repos/{GITHUB_REPO}/actions/runs",
            {"status": "in_progress", "per_page": 20},
            ttl=LIVE_CACHE_TTL,
        )
        runs = queued.get("workflow_runs", []) + in_prog.get("workflow_runs", [])
        if runs:
            return sorted(runs, key=lambda r: r.get("created_at", ""))

        recent = await _get(
            f"/repos/{GITHUB_REPO}/actions/runs",
            {"per_page": 5},
            ttl=LIVE_CACHE_TTL,
        )
        fallback = recent.get("workflow_runs", [])
        for r in fallback:
            r["is_recent_fallback"] = True
        return fallback
    except Exception:
        return []


@dataclass(frozen=True)
class MergedPRWindow:
    """Merged PRs for a time window, plus whether we actually got all of them."""

    prs: list[dict]
    since: str
    total_reported: int
    complete: bool

    @property
    def missing(self) -> int:
        return max(self.total_reported - len(self.prs), 0)


_SEARCH_PAGE_LIMIT = 10


def _search_item_to_pr(item: dict) -> dict:
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

    Search has a low secondary rate limit — cache with CACHE_TTL, not LIVE.
    """
    from datetime import UTC, datetime, timedelta

    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f"repo:{GITHUB_REPO} is:pr is:merged merged:>={since[:10]}"

    items: list[dict] = []
    total = 0
    try:
        for page in range(1, _SEARCH_PAGE_LIMIT + 1):
            data = await _get(
                "/search/issues",
                {
                    "q": query,
                    "per_page": "100",
                    "page": str(page),
                    "sort": "created",
                    "order": "desc",
                    "advanced_search": "true",
                },
                ttl=CACHE_TTL,
            )
            total = data.get("total_count", 0)
            batch = data.get("items", []) or []
            items.extend(batch)
            if not batch or len(items) >= total:
                break
    except Exception:
        return MergedPRWindow(prs=[], since=since, total_reported=0, complete=False)

    prs = [p for p in map(_search_item_to_pr, items) if p["merged_at"] >= since]
    return MergedPRWindow(
        prs=prs,
        since=since,
        total_reported=total,
        complete=len(items) >= total,
    )
