import asyncio
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import github_client as gh
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from status_reader import format_duration, get_agent_status
from wo_parser import (
    WOSpec,
    extract_wo_number_from_branch,
    extract_wo_number_from_pr_title,
    parse_wo_file,
)

app = FastAPI(title="AI Factory Status")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

SITE_TITLE = os.getenv("SITE_TITLE", "AI Factory Status")
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "60"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WATCHDOG_PATH = Path(os.getenv("WATCHDOG_PATH", "/watchdog/watchdog.json"))


def _load_watchdog() -> dict | None:
    if not WATCHDOG_PATH.exists():
        return None
    try:
        data = json.loads(WATCHDOG_PATH.read_text())
        generated = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        age_seconds = (datetime.now(UTC) - generated).total_seconds()
        stale_threshold = int(os.getenv("POLL_INTERVAL", "300")) * 2
        if age_seconds > stale_threshold:
            return None
        return data
    except Exception:
        return None


async def _load_wos() -> dict[int, WOSpec]:
    try:
        files = await gh.list_wo_files()
    except Exception:
        return {}
    results: dict[int, WOSpec] = {}
    contents = await asyncio.gather(
        *[gh.get_file_content(f["path"]) for f in files], return_exceptions=True
    )
    for f, content in zip(files, contents):
        if isinstance(content, Exception):
            continue
        spec = parse_wo_file(content, f["name"])
        if spec:
            results[spec.number] = spec
    return results


async def _load_active_branches() -> list[dict]:
    try:
        branches = await gh.list_branches()
    except Exception:
        return []
    wo_branches = [b for b in branches if b["name"].startswith("wo/")]
    results = []
    for b in wo_branches:
        wo_num = extract_wo_number_from_branch(b["name"])
        agent_status = None
        if wo_num:
            agent_status = await get_agent_status(b["name"], wo_num)
        commit = b.get("commit", {})
        committer = commit.get("commit", {}).get("committer", {})
        results.append(
            {
                "branch": b["name"],
                "wo_number": wo_num,
                "last_commit_sha": commit.get("sha", "")[:7],
                "last_commit_date": committer.get("date", ""),
                "last_commit_ago": (
                    format_duration(committer.get("date", ""))
                    if committer.get("date")
                    else "unknown"
                ),
                "agent_status": agent_status,
            }
        )
    return sorted(results, key=lambda x: x["last_commit_date"], reverse=True)


async def _load_open_prs() -> list[dict]:
    try:
        prs = await gh.list_open_prs()
    except Exception:
        return []
    results = []
    for pr in prs:
        wo_num = extract_wo_number_from_pr_title(pr.get("title", ""))
        checks = await gh.get_pr_checks(pr["number"])
        passing = sum(1 for c in checks if c.get("conclusion") == "success")
        failing = sum(1 for c in checks if c.get("conclusion") in ("failure", "timed_out"))
        pending = sum(1 for c in checks if c.get("status") in ("queued", "in_progress"))
        created = pr.get("created_at", "")
        results.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "author": pr.get("user", {}).get("login", ""),
                "wo_number": wo_num,
                "url": pr.get("html_url", ""),
                "created_at": created,
                "age": format_duration(created) if created else "unknown",
                "labels": [l["name"] for l in pr.get("labels", [])],
                "checks_passing": passing,
                "checks_failing": failing,
                "checks_pending": pending,
                "checks_total": len(checks),
                "ci_state": (
                    "failing"
                    if failing
                    else ("pending" if pending else "passing") if checks else "unknown"
                ),
            }
        )
    return sorted(results, key=lambda x: x["created_at"])


async def _load_ci_health() -> dict:
    try:
        runs = await gh.list_ci_runs()
    except Exception:
        return {"runs": [], "pass_rate": None, "error": True}
    recent = []
    for r in runs[:20]:
        recent.append(
            {
                "id": r.get("id"),
                "name": r.get("name", ""),
                "branch": r.get("head_branch", ""),
                "status": r.get("status", ""),
                "conclusion": r.get("conclusion"),
                "url": r.get("html_url", ""),
                "created_at": r.get("created_at", ""),
                "ago": (
                    format_duration(r.get("created_at", "")) if r.get("created_at") else "unknown"
                ),
                "duration_s": None,
            }
        )
    completed = [r for r in runs if r.get("conclusion")]
    pass_rate = None
    if completed:
        passed = sum(1 for r in completed if r.get("conclusion") == "success")
        pass_rate = round(passed / len(completed) * 100)
    return {"runs": recent, "pass_rate": pass_rate, "error": False}


def _apply_live_status(wos: dict[int, WOSpec], branches: list[dict], prs: list[dict]) -> None:
    branch_wo_map = {b["wo_number"]: b["branch"] for b in branches if b["wo_number"]}
    pr_wo_map: dict[int, dict] = {}
    for pr in prs:
        if pr["wo_number"]:
            pr_wo_map[pr["wo_number"]] = pr

    for num, spec in wos.items():
        if num in pr_wo_map:
            pr = pr_wo_map[num]
            if pr["ci_state"] == "failing":
                spec.status = "🔴 Blocked (CI failing)"
            elif pr["ci_state"] == "pending":
                spec.status = "👀 In Review (CI running)"
            else:
                spec.status = "👀 In Review (ready)"
        elif num in branch_wo_map:
            spec.status = "🔄 In Progress"


def _board_columns(wos: dict[int, WOSpec]) -> dict[str, list[WOSpec]]:
    cols: dict[str, list[WOSpec]] = defaultdict(list)
    for spec in sorted(wos.values(), key=lambda s: s.number, reverse=True):
        cols[spec.board_column].append(spec)
    return cols


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "site_title": SITE_TITLE,
                "message": "GITHUB_TOKEN and GITHUB_REPO environment variables are required.",
            },
        )

    wos, branches, prs, ci = await asyncio.gather(
        _load_wos(),
        _load_active_branches(),
        _load_open_prs(),
        _load_ci_health(),
    )

    _apply_live_status(wos, branches, prs)
    columns = _board_columns(wos)
    watchdog = _load_watchdog()

    # Derive health status from watchdog data
    if watchdog:
        s = watchdog.get("summary", {})
        errors = s.get("errors", 0)
        warnings = s.get("warnings", 0)
        runners_online = s.get("runners_online", 0)
        runners_busy = s.get("runners_busy", 0)
        if errors > 0 or (runners_online > 0 and runners_busy >= runners_online and errors > 0):
            health_status = "critical"
        elif warnings > 0 or (runners_online > 0 and runners_busy >= runners_online):
            health_status = "degraded"
        else:
            health_status = "healthy"
    else:
        health_status = "unknown"

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "site_title": SITE_TITLE,
            "refresh_seconds": REFRESH_SECONDS,
            "github_repo": GITHUB_REPO,
            "columns": {
                "open": columns.get("open", []),
                "in_progress": columns.get("in_progress", []),
                "review": columns.get("review", []),
                "blocked": columns.get("blocked", []),
                "done": columns.get("done", [])[:20],
            },
            "branches": branches,
            "prs": prs,
            "ci": ci,
            "total_wos": len(wos),
            "done_count": len(columns.get("done", [])),
            "watchdog": watchdog,
            "health_status": health_status,
        },
    )


@app.get("/wo/{number}", response_class=HTMLResponse)
async def wo_detail(request: Request, number: int):
    files = await gh.list_wo_files()
    match = next((f for f in files if f["name"].startswith(f"WO-{number}-")), None)
    if not match:
        return HTMLResponse("<h1>WO not found</h1>", status_code=404)
    content = await gh.get_file_content(match["path"])
    spec = parse_wo_file(content, match["name"])
    return templates.TemplateResponse(
        request=request,
        name="wo_detail.html",
        context={"site_title": SITE_TITLE, "spec": spec, "refresh_seconds": 300},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "repo": GITHUB_REPO, "token_set": bool(GITHUB_TOKEN)}
