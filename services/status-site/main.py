import asyncio
import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import github_client as gh
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
ORCHESTRATOR_PATH = Path(os.getenv("ORCHESTRATOR_PATH", "/orchestrator/orchestrator.json"))
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8100")
VALIDATIONS_PATH = Path("/orchestrator/pending_validations.json")
PLAN_PATH = os.getenv("PLAN_PATH", "docs/factory/PLAN.json")
FACTORY_CONFIG_PATH = Path(os.getenv("FACTORY_CONFIG_PATH", "/config/factory-config.json"))


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


def _load_orchestrator() -> dict | None:
    """Load orchestrator state — stale after 2× POLL_INTERVAL (dispatch/agent data)."""
    if not ORCHESTRATOR_PATH.exists():
        return None
    try:
        data = json.loads(ORCHESTRATOR_PATH.read_text())
        generated = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        stale_secs = int(os.getenv("POLL_INTERVAL", "300")) * 2
        if (datetime.now(UTC) - generated).total_seconds() > stale_secs:
            return None
        return data
    except Exception:
        return None


def _load_orchestrator_file() -> dict | None:
    """Load orchestrator state file without a staleness check — for plan/milestone data."""
    if not ORCHESTRATOR_PATH.exists():
        return None
    try:
        return json.loads(ORCHESTRATOR_PATH.read_text())
    except Exception:
        return None


def _load_plan_from_orchestrator() -> dict | None:
    """Return the plan sub-dict — uses the no-staleness loader so plan is always shown."""
    orch = _load_orchestrator_file()
    if not orch:
        return None
    plan = orch.get("plan")
    if not plan or not plan.get("loaded"):
        return None
    return plan


def _load_validations() -> list[dict]:
    """Read pending validations from the orchestrator volume."""
    if not VALIDATIONS_PATH.exists():
        return []
    try:
        return json.loads(VALIDATIONS_PATH.read_text())
    except Exception:
        return []


async def _fetch_plan_from_github() -> dict | None:
    """Fallback: fetch PLAN.json directly from GitHub when orchestrator is offline."""
    try:
        content = await gh.get_file_content(PLAN_PATH)
        return json.loads(content)
    except Exception:
        return None


async def _load_wos() -> tuple[dict[int, WOSpec], bool]:
    try:
        files = await gh.list_wo_files()
    except Exception:
        return {}, False
    results: dict[int, WOSpec] = {}
    contents = await asyncio.gather(
        *[gh.get_file_content(f["path"]) for f in files], return_exceptions=True
    )
    for f, content in zip(files, contents):
        if isinstance(content, Exception):
            continue
        spec = parse_wo_file(content, f["name"], repo=GITHUB_REPO)
        if spec:
            results[spec.number] = spec

    # Load WOs from secondary repos registered via Settings → Projects
    cfg = _load_factory_config()
    for project in cfg.get("projects", []):
        repo = project.get("repo", "")
        wo_path = project.get("wo_path", "") or WO_PATH
        if not repo:
            continue
        try:
            sec_files = await gh.list_wo_files_for(repo, wo_path)
        except Exception as e:
            print(f"[status-site] Could not list WOs for {repo}: {e}")
            continue
        sec_contents = await asyncio.gather(
            *[gh.get_file_content_for(repo, f["path"]) for f in sec_files],
            return_exceptions=True,
        )
        for f, content in zip(sec_files, sec_contents):
            if isinstance(content, Exception):
                continue
            spec = parse_wo_file(content, f["name"], repo=repo)
            if spec:
                results[spec.number] = spec

    return results, True


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
    branch_wo_map = {b["wo_number"]: b for b in branches if b["wo_number"]}
    pr_wo_map: dict[int, dict] = {}
    for pr in prs:
        if pr["wo_number"]:
            pr_wo_map[pr["wo_number"]] = pr

    for num, spec in wos.items():
        if num in pr_wo_map:
            pr = pr_wo_map[num]
            spec.pr_number = pr["number"]
            spec.ci_state = pr["ci_state"]
            if pr["ci_state"] == "failing":
                spec.status = "🔴 Blocked (CI failing)"
            elif pr["ci_state"] == "pending":
                spec.status = "👀 In Review (CI running)"
            else:
                spec.status = "👀 In Review (ready)"
        elif num in branch_wo_map:
            spec.status = "🔄 In Progress"
            b = branch_wo_map[num]
            if b.get("agent_status"):
                spec.agent_name = b["agent_status"].get("agent", "")
                spec.agent_step = b["agent_status"].get("step", "")


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

    wos_result, branches, prs, ci = await asyncio.gather(
        _load_wos(),
        _load_active_branches(),
        _load_open_prs(),
        _load_ci_health(),
    )
    wos, wos_available = wos_result

    _apply_live_status(wos, branches, prs)
    columns = _board_columns(wos)
    watchdog = _load_watchdog()
    validations = _load_validations()
    pending_validations = [v for v in validations if v.get("status") == "pending"]

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
            "wos_available": wos_available,
            "pending_validations": pending_validations,
        },
    )


@app.get("/wo/{number}", response_class=HTMLResponse)
async def wo_detail(request: Request, number: int):
    try:
        files = await gh.list_wo_files()
        match = next((f for f in files if f["name"].startswith(f"WO-{number}-")), None)
        if not match:
            return HTMLResponse(
                f"<h1 style='font-family:monospace;padding:2rem'>WO-{number} not found</h1>",
                status_code=404,
            )
        content = await gh.get_file_content(match["path"])
        spec = parse_wo_file(content, match["name"])
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "site_title": SITE_TITLE,
                "message": f"Could not load WO-{number}: {exc}",
                "refresh_seconds": 60,
            },
            status_code=502,
        )
    return templates.TemplateResponse(
        request=request,
        name="wo_detail.html",
        context={"site_title": SITE_TITLE, "spec": spec, "refresh_seconds": 300, "github_repo": GITHUB_REPO},
    )


@app.get("/pm", response_class=HTMLResponse)
async def pm_dashboard(request: Request):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return templates.TemplateResponse(request=request, name="error.html", context={
            "site_title": SITE_TITLE, "message": "GITHUB_TOKEN and GITHUB_REPO required."
        })

    wos_result, branches, prs, merged_prs = await asyncio.gather(
        _load_wos(),
        _load_active_branches(),
        _load_open_prs(),
        gh.list_merged_prs(days=56),
    )
    wos, wos_available = wos_result
    _apply_live_status(wos, branches, prs)
    columns = _board_columns(wos)
    watchdog = _load_watchdog()

    # Program roll-ups
    programs: dict[str, dict] = defaultdict(lambda: {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "in_review": 0, "open": 0})
    for spec in wos.values():
        prog = spec.program or "Standalone"
        programs[prog]["total"] += 1
        programs[prog][spec.board_column if spec.board_column != "review" else "in_review"] += 1

    for prog in programs.values():
        total = prog["total"]
        prog["pct"] = round(prog["done"] / total * 100) if total else 0

    # Velocity: WOs merged per week over last 8 weeks
    velocity: list[dict] = []
    now = datetime.now(UTC)
    for i in range(7, -1, -1):
        week_start = now - timedelta(weeks=i + 1)
        week_end = now - timedelta(weeks=i)
        count = sum(
            1 for p in merged_prs
            if p.get("merged_at") and week_start.isoformat() <= p["merged_at"] <= week_end.isoformat()
        )
        velocity.append({
            "label": week_start.strftime("%-d %b"),
            "count": count,
            "bar": "█" * count if count else "·",
        })

    # Velocity projection
    recent_counts = [w["count"] for w in velocity[-4:]]
    avg_velocity = sum(recent_counts) / max(len(recent_counts), 1)
    remaining_open = len(columns.get("open", [])) + len(columns.get("in_progress", [])) + len(columns.get("review", []))
    weeks_to_done = (remaining_open / avg_velocity) if avg_velocity > 0 else None
    projected_done = (now + timedelta(weeks=weeks_to_done)).date().isoformat() if weeks_to_done is not None else None

    plan_data = _load_plan_from_orchestrator()
    milestone_projections: list[dict] = []
    if plan_data and avg_velocity > 0:
        all_plan_wos = plan_data.get("all_wos") or plan_data.get("queue", [])
        for ms in plan_data.get("milestones", []):
            ms_id = ms["id"]
            ms_wos = [w for w in all_plan_wos if ms_id in w.get("blocks_milestones", [])]
            remaining = sum(1 for w in ms_wos if w.get("status", "open").lower() not in {"done", "complete"})
            weeks_needed = remaining / avg_velocity
            proj_date = (now + timedelta(weeks=weeks_needed)).date()
            target_str = ms.get("target_date")
            target_date = None
            if target_str:
                try:
                    from datetime import date as _date
                    target_date = _date.fromisoformat(target_str)
                except Exception:
                    pass
            if target_date:
                days_delta = (target_date - proj_date).days
                if days_delta >= 14:
                    status = "on_track"
                elif days_delta >= 0:
                    status = "close"
                else:
                    status = "at_risk"
            else:
                status = "unknown"
            milestone_projections.append({
                "id": ms_id,
                "label": ms["label"],
                "target_date": target_str,
                "remaining_wos": remaining,
                "projected_date": proj_date.isoformat(),
                "status": status,
                "days_delta": (target_date - proj_date).days if target_date else None,
            })

    velocity_summary = {
        "avg_per_week": round(avg_velocity, 1),
        "remaining_open": remaining_open,
        "projected_done": projected_done,
        "milestone_projections": milestone_projections,
    }

    # Blocked items from watchdog
    blocked_alerts = [a for a in (watchdog or {}).get("alerts", []) if a.get("severity") == "error" and a.get("pr_number")]

    # Active agents from branches
    active_agents = [b for b in branches if b.get("agent_status")]

    orchestrator = _load_orchestrator()
    validations = _load_validations()
    pending_validations = [v for v in validations if v.get("status") == "pending"]

    return templates.TemplateResponse(request=request, name="pm.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": REFRESH_SECONDS,
        "github_repo": GITHUB_REPO,
        "columns": {k: columns.get(k, []) for k in ("open", "in_progress", "review", "blocked", "done")},
        "total_wos": len(wos),
        "done_count": len(columns.get("done", [])),
        "programs": dict(sorted(programs.items())),
        "velocity": velocity,
        "velocity_summary": velocity_summary,
        "blocked_alerts": blocked_alerts,
        "active_agents": active_agents,
        "watchdog": watchdog,
        "orchestrator": orchestrator,
        "wos_available": wos_available,
        "pending_validations": pending_validations,
    })


@app.get("/ci", response_class=HTMLResponse)
async def ci_dashboard(request: Request):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return templates.TemplateResponse(request=request, name="error.html", context={
            "site_title": SITE_TITLE, "message": "GITHUB_TOKEN and GITHUB_REPO required."
        })

    prs, runners, active_runs, ci = await asyncio.gather(
        _load_open_prs(),
        gh.list_runners(),
        gh.list_active_runs(),
        _load_ci_health(),
    )
    watchdog = _load_watchdog()

    # Per-check breakdown for each PR with flaky detection
    pr_checks: list[dict] = []
    for pr in prs:
        raw_checks = await gh.get_pr_checks(pr["number"])
        checks_detail = []
        is_flaky = False
        for c in raw_checks:
            attempts = c.get("app", {}).get("name", "")
            conclusion = c.get("conclusion")
            status = c.get("status")
            started = c.get("started_at")
            completed = c.get("completed_at")
            duration_s = None
            if started and completed:
                try:
                    s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    e = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                    duration_s = int((e - s).total_seconds())
                except Exception:
                    pass
            checks_detail.append({
                "name": c.get("name", ""),
                "status": status,
                "conclusion": conclusion,
                "duration_s": duration_s,
                "url": c.get("html_url", ""),
            })
        pr_checks.append({
            "number": pr["number"],
            "title": pr["title"],
            "url": pr["url"],
            "wo_number": pr["wo_number"],
            "age": pr["age"],
            "ci_state": pr["ci_state"],
            "auto_merge": pr.get("auto_merge", False),
            "checks": checks_detail,
            "is_flaky": is_flaky,
        })

    # CI timing stats from last 20 runs
    completed_runs = [r for r in ci.get("runs", []) if r.get("conclusion")]
    avg_duration = None

    # Runner utilization
    runners_busy = [r for r in runners if r.get("busy")]
    runners_free = [r for r in runners if not r.get("busy") and r.get("status") == "online"]

    return templates.TemplateResponse(request=request, name="ci.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": REFRESH_SECONDS,
        "github_repo": GITHUB_REPO,
        "runners": runners,
        "runners_busy": runners_busy,
        "runners_free": runners_free,
        "active_runs": active_runs[:10],
        "pr_checks": pr_checks,
        "ci": ci,
        "watchdog": watchdog,
    })


def _compute_plan_stats(plan_data: dict) -> dict:
    """
    Pre-compute milestone and phase progress stats server-side so the
    template doesn't need Jinja2 tests that aren't available (e.g. 'containing').
    Uses all_wos (full PLAN.json queue including done/in_progress) for accurate %.
    Returns an augmented plan_data copy with milestone_stats and phase_stats.
    """
    all_wos = plan_data.get("all_wos") or plan_data.get("queue", [])
    milestones = plan_data.get("milestones", [])
    phases = plan_data.get("phases", [])

    # Milestone stats: count WOs that block each milestone
    milestone_stats: dict[str, dict] = {}
    for ms in milestones:
        ms_id = ms["id"]
        ms_wos = [w for w in all_wos if ms_id in w.get("blocks_milestones", [])]
        ms_done = [w for w in ms_wos if w.get("status", "").lower() in {"done", "complete"}]
        total = len(ms_wos)
        pct = round(len(ms_done) / total * 100) if total else 0
        milestone_stats[ms_id] = {
            "total": total,
            "done": len(ms_done),
            "pct": pct,
        }

    # Phase stats: count WOs per phase
    phase_stats: dict[str, dict] = {}
    for phase in phases:
        ph_id = phase["id"]
        ph_wos = [w for w in all_wos if w.get("phase") == ph_id]
        ph_done = [w for w in ph_wos if w.get("status", "").lower() in {"done", "complete"}]
        total = len(ph_wos)
        pct = round(len(ph_done) / total * 100) if total else 0
        phase_stats[ph_id] = {
            "total": total,
            "done": len(ph_done),
            "pct": pct,
            "wos": [w["wo"] for w in ph_wos],
        }

    result = dict(plan_data)
    result["milestone_stats"] = milestone_stats
    result["phase_stats"] = phase_stats
    return result


@app.get("/plan", response_class=HTMLResponse)
async def plan_dashboard(request: Request):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return templates.TemplateResponse(request=request, name="error.html", context={
            "site_title": SITE_TITLE, "message": "GITHUB_TOKEN and GITHUB_REPO required."
        })

    plan_from_orch = _load_plan_from_orchestrator()
    if plan_from_orch:
        raw_plan = plan_from_orch
        plan_source = "orchestrator"
    else:
        raw = await _fetch_plan_from_github()
        if raw:
            raw_plan = {
                "loaded": True,
                "next": None,
                "queue": raw.get("queue", []),
                "all_wos": raw.get("queue", []),
                "deferred": raw.get("deferred", []),
                "milestones": raw.get("milestones", []),
                "phases": raw.get("phases", []),
                "last_updated": raw.get("last_updated"),
            }
        else:
            raw_plan = None
        plan_source = "github" if raw else "unavailable"

    plan_data = _compute_plan_stats(raw_plan) if raw_plan else None
    orchestrator = _load_orchestrator()

    return templates.TemplateResponse(request=request, name="plan.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": REFRESH_SECONDS,
        "github_repo": GITHUB_REPO,
        "plan": plan_data,
        "plan_source": plan_source,
        "orchestrator": orchestrator,
    })


@app.get("/api/plan")
async def api_plan():
    """Return the full plan including phases, milestones, sorted queue, and next WO."""
    plan = _load_plan_from_orchestrator()
    if plan:
        return JSONResponse(content=plan)
    raw = await _fetch_plan_from_github()
    if not raw:
        raise HTTPException(status_code=503, detail="Plan unavailable — orchestrator offline and GitHub fetch failed")
    return JSONResponse(content={
        "loaded": True,
        "source": "github_direct",
        "last_updated": raw.get("last_updated"),
        "milestones": raw.get("milestones", []),
        "phases": raw.get("phases", []),
        "queue": raw.get("queue", []),
        "next": None,  # can't compute without plan_engine in this container
    })


@app.get("/api/plan/next")
async def api_plan_next():
    """Return the highest-priority open, unblocked WO from the plan queue."""
    plan = _load_plan_from_orchestrator()
    if plan and plan.get("next") is not None:
        return JSONResponse(content=plan["next"])
    # Fallback: if orchestrator is offline, return first open item from raw plan
    raw = await _fetch_plan_from_github()
    if not raw:
        raise HTTPException(status_code=503, detail="Plan unavailable")
    queue = raw.get("queue", [])
    for item in queue:
        status = item.get("status", "open").lower()
        if status not in {"done", "deferred", "claimed", "in_progress", "review"}:
            deps = item.get("depends_on", [])
            if not deps:
                return JSONResponse(content=item)
    raise HTTPException(status_code=404, detail="No eligible WO found in queue")


@app.patch("/api/plan/wos/{wo}")
async def api_plan_patch_wo(wo: str, request: Request):
    """
    Stub: accept priority/phase/pin changes for a WO.
    Full GitHub write-back is out of scope for WO-358; returns 200 with the
    received payload so agents can confirm the endpoint is wired.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    return JSONResponse(content={
        "ok": True,
        "wo": wo,
        "applied": body,
        "note": "Write-back to GitHub PLAN.json is pending (WO-359). Changes accepted but not persisted.",
    })


@app.post("/api/validations/{wo}/approve")
async def proxy_approve(wo: str, request: Request):
    """Proxy approve decision to the orchestrator API."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    body.setdefault("decided_by", "human")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/validations/{wo}/approve", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Orchestrator unreachable: {e}")


@app.post("/api/validations/{wo}/reject")
async def proxy_reject(wo: str, request: Request):
    """Proxy reject decision to the orchestrator API."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    body.setdefault("decided_by", "human")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/validations/{wo}/reject", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Orchestrator unreachable: {e}")


def _load_factory_config() -> dict:
    if not FACTORY_CONFIG_PATH.exists():
        return {"projects": [], "created_at": None}
    try:
        return json.loads(FACTORY_CONFIG_PATH.read_text())
    except Exception:
        return {"projects": [], "created_at": None}


def _save_factory_config(cfg: dict) -> None:
    FACTORY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTORY_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


@app.get("/settings", response_class=HTMLResponse)
async def settings_root(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": 3600,
        "github_repo": GITHUB_REPO,
    })


@app.get("/settings/projects", response_class=HTMLResponse)
async def settings_projects(request: Request, saved: str = "", error: str = ""):
    cfg = _load_factory_config()
    return templates.TemplateResponse(request=request, name="settings_projects.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": 3600,
        "github_repo": GITHUB_REPO,
        "projects": cfg.get("projects", []),
        "saved": saved,
        "error": error,
    })


@app.post("/settings/projects/add", response_class=HTMLResponse)
async def settings_projects_add(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    repo = str(form.get("repo", "")).strip()
    label = str(form.get("label", "")).strip()
    wo_path = str(form.get("wo_path", "docs/project_management/work_orders")).strip()
    plan_path = str(form.get("plan_path", "docs/factory/PLAN.json")).strip()

    if not repo or "/" not in repo:
        return RedirectResponse(url="/settings/projects?error=Invalid+repo+format+%28owner%2Frepo%29", status_code=303)

    cfg = _load_factory_config()
    projects = cfg.get("projects", [])

    if any(p["repo"] == repo for p in projects):
        return RedirectResponse(url=f"/settings/projects?error=Project+{repo}+already+exists", status_code=303)

    projects.append({
        "repo": repo,
        "label": label or repo.split("/")[1],
        "wo_path": wo_path,
        "plan_path": plan_path,
        "added_at": datetime.now(UTC).isoformat(),
    })
    cfg["projects"] = projects
    _save_factory_config(cfg)
    return RedirectResponse(url=f"/settings/projects?saved={repo}", status_code=303)


@app.post("/settings/projects/remove", response_class=HTMLResponse)
async def settings_projects_remove(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    repo = str(form.get("repo", "")).strip()
    cfg = _load_factory_config()
    cfg["projects"] = [p for p in cfg.get("projects", []) if p["repo"] != repo]
    _save_factory_config(cfg)
    return RedirectResponse(url="/settings/projects?saved=removed", status_code=303)


@app.get("/health")
async def health():
    return {"status": "ok", "repo": GITHUB_REPO, "token_set": bool(GITHUB_TOKEN)}
