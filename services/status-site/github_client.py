import base64
import os
import time
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


async def list_merged_prs(days: int = 56) -> list[dict]:
    """A single page sorted by 'updated' silently drops PRs merged within the
    window but with no post-merge activity (comments, label changes) — they
    get pushed off the top-100 by newer, unrelated PR activity even though
    they're well inside `days`. Sort by 'created' instead (a much better
    proxy for merge recency — not perturbed by post-merge noise) and
    paginate across several pages rather than trusting a single page of 100
    to contain everything in the window."""
    try:
        from datetime import UTC, datetime, timedelta
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        results: list[dict] = []
        for page in range(1, 6):  # up to 500 PRs — generous for a 56-day window
            data = await _get(
                f"/repos/{GITHUB_REPO}/pulls",
                {"state": "closed", "per_page": 100, "page": page, "sort": "created", "direction": "desc"},
            )
            if not data:
                break
            results.extend(p for p in data if p.get("merged_at") and p["merged_at"] >= since)
            if len(data) < 100:
                break  # last page
        return results
    except Exception:
        return []
