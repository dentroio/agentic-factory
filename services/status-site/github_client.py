import base64
import os
import time
from typing import Any

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
RUNS_PATH = os.getenv("RUNS_PATH", "docs/factory/runs")
CACHE_TTL = 60

_cache: dict[str, tuple[float, Any]] = {}


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def _get(path: str, params: dict | None = None) -> Any:
    cache_key = f"{path}?{params}"
    if cache_key in _cache:
        ts, val = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return val

    url = f"https://api.github.com{path}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        val = resp.json()

    _cache[cache_key] = (time.time(), val)
    return val


async def list_wo_files() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/contents/{WO_PATH}"
    items = await _get(path)
    return [i for i in items if i["name"].endswith(".md") and i["name"].startswith("WO-")]


async def get_file_content(file_path: str) -> str:
    path = f"/repos/{GITHUB_REPO}/contents/{file_path}"
    data = await _get(path)
    return base64.b64decode(data["content"]).decode("utf-8")


async def list_open_prs() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/pulls"
    return await _get(path, {"state": "open", "per_page": 100})


async def list_branches() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/branches"
    return await _get(path, {"per_page": 100})


async def list_ci_runs() -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/actions/runs"
    data = await _get(path, {"per_page": 30})
    return data.get("workflow_runs", [])


async def get_branch_file(branch: str, file_path: str) -> str | None:
    path = f"/repos/{GITHUB_REPO}/contents/{file_path}"
    try:
        data = await _get(f"{path}?ref={branch}")
        return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        return None


async def get_pr_checks(pr_number: int) -> list[dict]:
    path = f"/repos/{GITHUB_REPO}/pulls/{pr_number}/commits"
    try:
        commits = await _get(path)
        if not commits:
            return []
        sha = commits[-1]["sha"]
        checks_path = f"/repos/{GITHUB_REPO}/commits/{sha}/check-runs"
        data = await _get(checks_path)
        return data.get("check_runs", [])
    except Exception:
        return []
