import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import github_client as gh
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
LOG_PATH = os.getenv("LOG_PATH", "/var/log/factory-agent/out.log")
FACTORY_CONFIG_PATH = Path(os.getenv("FACTORY_CONFIG_PATH", "/config/factory-config.json"))
LOCAL_REPO_MOUNT = os.getenv("LOCAL_REPO_MOUNT", "")


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


def _load_wos_from_disk() -> dict[int, WOSpec] | None:
    """Read WO markdown files directly from the locally-mounted repo volume.

    Returns a populated dict when the mount is available, None when it isn't.
    Eliminates ~390 GitHub API calls per page load (1 list + N individual fetches).
    """
    if not LOCAL_REPO_MOUNT:
        return None
    wo_dir = Path(LOCAL_REPO_MOUNT) / WO_PATH
    if not wo_dir.is_dir():
        return None
    results: dict[int, WOSpec] = {}
    for path in wo_dir.glob("WO-*.md"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        spec = parse_wo_file(content, path.name, repo=GITHUB_REPO)
        if spec:
            results[spec.number] = spec
    return results


async def _load_wos() -> tuple[dict[int, WOSpec], bool]:
    # Prefer reading from the locally-mounted repo — zero GitHub API calls.
    disk_results = _load_wos_from_disk()
    if disk_results is not None:
        results = disk_results
    else:
        try:
            files = await gh.list_wo_files()
        except Exception:
            return {}, False
        results = {}
        contents = await asyncio.gather(
            *[gh.get_file_content(f["path"]) for f in files], return_exceptions=True
        )
        for f, content in zip(files, contents):
            if isinstance(content, Exception):
                continue
            spec = parse_wo_file(content, f["name"], repo=GITHUB_REPO)
            if spec:
                results[spec.number] = spec

    # Load WOs from secondary repos registered via Settings → Projects (always GitHub)
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
            if spec and spec.number not in results:  # never overwrite primary-repo WOs
                results[spec.number] = spec

    return results, True


async def _load_active_branches() -> list[dict]:
    try:
        branches = await gh.list_branches()
    except Exception:
        return []
    wo_branches = [b for b in branches if b["name"].startswith("wo/")]

    async def _enrich(b: dict) -> dict:
        wo_num = extract_wo_number_from_branch(b["name"])
        agent_status = None
        if wo_num:
            try:
                agent_status = await get_agent_status(b["name"], wo_num)
            except Exception:
                pass
        commit = b.get("commit", {})
        committer = commit.get("commit", {}).get("committer", {})
        return {
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

    results = await asyncio.gather(*[_enrich(b) for b in wo_branches], return_exceptions=False)
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



def _apply_live_status(
    wos: dict[int, WOSpec],
    branches: list[dict],
    prs: list[dict],
    dispatch: dict | None = None,
    merged_prs: list[dict] | None = None,
) -> None:
    branch_wo_map = {b["wo_number"]: b for b in branches if b["wo_number"]}
    pr_wo_map: dict[int, dict] = {}
    for pr in prs:
        if pr["wo_number"]:
            pr_wo_map[pr["wo_number"]] = pr

    # Build set of WO numbers with merged PRs — authoritative "done" signal.
    merged_wo_nums: set[int] = set()
    for p in (merged_prs or []):
        m = re.search(r"WO-(\d+)", p.get("title", ""))
        if m:
            merged_wo_nums.add(int(m.group(1)))
        if p.get("merged_at"):
            m2 = re.search(r"wo[/-](\d+)", p.get("head", {}).get("ref", ""), re.I)
            if m2:
                merged_wo_nums.add(int(m2.group(1)))

    # Build a map from WO number → dispatch entry so we can mark active WOs
    # even when the branch hasn't been pushed to GitHub yet (which is the normal
    # case during agent work — branches are local-only until the PR is created).
    dispatch_map: dict[int, dict] = {}
    for wo_id, entry in (dispatch or {}).items():
        try:
            num = int(re.sub(r"[^0-9]", "", wo_id))
            dispatch_map[num] = entry
        except (ValueError, TypeError):
            pass

    for num, spec in wos.items():
        # Merged PRs are the strongest signal — always wins over spec-file status.
        if num in merged_wo_nums:
            spec.status = "✅ Done"
            spec.merged_at = next(
                (p.get("merged_at", "") for p in (merged_prs or [])
                 if re.search(rf"WO-{num}\b", p.get("title", ""))),
                "",
            )
            continue
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
        elif num in dispatch_map:
            # Agent has this WO claimed locally (branch not yet on GitHub)
            entry = dispatch_map[num]
            agent_status = entry.get("status", "in_progress")
            # Complete WOs don't override whatever plan/spec status was set above
            if agent_status == "complete":
                pass
            else:
                step = entry.get("step", "")
                if agent_status == "awaiting_human":
                    spec.status = "⏳ Awaiting Review"
                elif "gate failed" in step:
                    spec.status = "❌ Gate Failed"
                else:
                    spec.status = "🔄 In Progress"
                # Prefer the backend field (actual AI, e.g. "cursor") over the
                # runner identity (e.g. "claude-runner") for display purposes.
                spec.agent_name = entry.get("backend") or entry.get("agent", "")


def _board_columns(wos: dict[int, WOSpec]) -> dict[str, list[WOSpec]]:
    cols: dict[str, list[WOSpec]] = defaultdict(list)
    for spec in sorted(wos.values(), key=lambda s: s.number, reverse=True):
        cols[spec.board_column].append(spec)
    # Sort done column by merged_at descending so recent completions appear first
    if "done" in cols:
        cols["done"].sort(key=lambda s: s.merged_at or "", reverse=True)
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

    async def _load_runner_status() -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{ORCHESTRATOR_URL}/api/backends")
                if r.status_code == 200:
                    return r.json().get("agent_runner_online", False)
        except Exception:
            pass
        return False

    async def _load_dispatch() -> dict:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{ORCHESTRATOR_URL}/api/dispatch")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return {}

    wos_result, branches, prs, merged_prs_board, ci, agent_runner_online, dispatch = await asyncio.gather(
        _load_wos(),
        _load_active_branches(),
        _load_open_prs(),
        gh.list_merged_prs(days=56),
        _load_ci_health(),
        _load_runner_status(),
        _load_dispatch(),
    )
    wos, wos_available = wos_result

    _apply_live_status(wos, branches, prs, dispatch, merged_prs=merged_prs_board)
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
                "planned": columns.get("planned", []),
                "open": columns.get("open", []),
                "in_progress": columns.get("in_progress", []),
                "review": columns.get("review", []),
                "blocked": columns.get("blocked", []),
                "deferred": columns.get("deferred", []),
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
            "agent_runner_online": agent_runner_online,
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
    # Load thread (non-fatal if orchestrator is down)
    thread_messages: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            t_resp = await client.get(f"{ORCHESTRATOR_URL}/api/thread/WO-{number}/messages")
            if t_resp.status_code == 200:
                thread_messages = t_resp.json()
    except Exception:
        pass

    # Extract peer review summary from thread
    _review_msgs = [m for m in thread_messages if m.get("type") == "review"]
    _final_msgs = [m for m in thread_messages
                   if m.get("author") == "claude-reviewer" and m.get("type") == "text"]
    _reviewer_map: dict[str, dict] = {}
    for m in _review_msgs:
        meta = m.get("metadata") or {}
        name = meta.get("reviewer", "unknown")
        _reviewer_map[name] = {
            "name": name,
            "backend": meta.get("backend", "?"),
            "passed": meta.get("passed", False),
            "findings": meta.get("findings") or [],
            "timestamp": m.get("timestamp", ""),
        }
    _chain_order = ["security", "architecture", "correctness", "performance", "documentation"]
    peer_review = {
        "has_reviews": bool(_reviewer_map),
        "reviewers": [_reviewer_map[k] for k in _chain_order if k in _reviewer_map]
                   + [v for k, v in _reviewer_map.items() if k not in _chain_order],
        "overall_passed": all(r["passed"] for r in _reviewer_map.values()) if _reviewer_map else None,
        "final_review": _final_msgs[-1] if _final_msgs else None,
    }

    return templates.TemplateResponse(
        request=request,
        name="wo_detail.html",
        context={
            "site_title": SITE_TITLE,
            "spec": spec,
            "refresh_seconds": 300,
            "github_repo": GITHUB_REPO,
            "thread_messages": thread_messages,
            "wo_id": f"WO-{number}",
            "peer_review": peer_review,
        },
    )


@app.get("/pm", response_class=HTMLResponse)
async def pm_dashboard(request: Request):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return templates.TemplateResponse(request=request, name="error.html", context={
            "site_title": SITE_TITLE, "message": "GITHUB_TOKEN and GITHUB_REPO required."
        })

    async def _pm_dispatch() -> dict:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{ORCHESTRATOR_URL}/api/dispatch")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return {}

    wos_result, branches, prs, merged_prs, dispatch = await asyncio.gather(
        _load_wos(),
        _load_active_branches(),
        _load_open_prs(),
        gh.list_merged_prs(days=56),
        _pm_dispatch(),
    )
    wos, wos_available = wos_result
    _apply_live_status(wos, branches, prs, dispatch, merged_prs=merged_prs)
    columns = _board_columns(wos)
    watchdog = _load_watchdog()

    # Program roll-ups — deferred WOs excluded from total/progress (tracked separately)
    programs: dict[str, dict] = defaultdict(lambda: {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "in_review": 0, "planned": 0, "open": 0, "deferred": 0})
    for spec in wos.values():
        prog = spec.program or "Standalone"
        col = spec.board_column if spec.board_column != "review" else "in_review"
        if col == "deferred":
            programs[prog]["deferred"] += 1
        else:
            programs[prog]["total"] += 1
            programs[prog][col] = programs[prog].get(col, 0) + 1

    for prog in programs.values():
        total = prog["total"]
        prog["pct"] = round(prog["done"] / total * 100) if total else 0

    # Per-program WO lists grouped by board column for expanded program cards
    program_wos: dict[str, dict] = defaultdict(lambda: {"planned": [], "open": [], "in_progress": [], "review": [], "blocked": [], "done": [], "deferred": []})
    for spec in wos.values():
        prog = spec.program or "Standalone"
        program_wos[prog][spec.board_column].append(spec)
    for prog_data in program_wos.values():
        for col_list in prog_data.values():
            col_list.sort(key=lambda s: s.number)

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
            # Use spec file board_column as the authority — not stale PLAN.json status fields.
            def _wo_num(wo_str: str) -> int | None:
                try:
                    return int(re.sub(r"[^0-9]", "", wo_str))
                except (ValueError, TypeError):
                    return None
            remaining = sum(
                1 for w in ms_wos
                if (n := _wo_num(w.get("wo", ""))) is None
                or n not in wos
                or wos[n].board_column not in ("done", "deferred")
            )
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
        "columns": {k: columns.get(k, []) for k in ("planned", "open", "in_progress", "review", "blocked", "done")},
        "total_wos": len(wos),
        "done_count": len(columns.get("done", [])),
        "programs": dict(sorted(programs.items())),
        "program_wos": dict(sorted(program_wos.items())),
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


def _compute_plan_stats(plan_data: dict, wos_spec: dict | None = None) -> dict:
    """
    Pre-compute milestone and phase progress stats server-side.
    Uses spec-file board_column (via wos_spec) as the authoritative live status.
    Falls back to checking whether the WO appears in the open queue.
    Returns an augmented plan_data copy with milestone_stats, milestone_wos,
    phase_stats, and phase_wos.
    """
    all_wos = plan_data.get("all_wos") or plan_data.get("queue", [])
    open_queue_ids = {w["wo"] for w in plan_data.get("queue", [])}
    milestones = plan_data.get("milestones", [])
    phases = plan_data.get("phases", [])

    def _live_status(wo_entry: dict) -> str:
        """Return authoritative board_column for a queue item."""
        if wos_spec:
            try:
                num = int(re.sub(r"[^0-9]", "", wo_entry.get("wo", "")))
                spec = wos_spec.get(num)
                if spec:
                    return spec.board_column
            except (ValueError, TypeError):
                pass
        # If not in the open/active queue, treat as done
        wo_id = wo_entry.get("wo", "")
        return "open" if wo_id in open_queue_ids else "done"

    # Milestone stats + per-milestone WO lists
    milestone_stats: dict[str, dict] = {}
    milestone_wos: dict[str, dict] = {}
    for ms in milestones:
        ms_id = ms["id"]
        ms_all = [w for w in all_wos if ms_id in (w.get("blocks_milestones") or [])]
        done_list, open_list = [], []
        for w in ms_all:
            status = _live_status(w)
            enriched = {**w, "_live_status": status}
            if status == "done":
                done_list.append(enriched)
            else:
                open_list.append(enriched)
        total = len(ms_all)
        pct = round(len(done_list) / total * 100) if total else 0
        milestone_stats[ms_id] = {"total": total, "done": len(done_list), "pct": pct}
        milestone_wos[ms_id] = {"done": done_list, "open": open_list}

    # Phase stats + per-phase WO lists
    phase_stats: dict[str, dict] = {}
    phase_wos: dict[str, dict] = {}
    for phase in phases:
        ph_id = phase["id"]
        ph_all = [w for w in all_wos if w.get("phase") == ph_id]
        done_list, open_list = [], []
        for w in ph_all:
            status = _live_status(w)
            enriched = {**w, "_live_status": status}
            if status == "done":
                done_list.append(enriched)
            else:
                open_list.append(enriched)
        total = len(ph_all)
        pct = round(len(done_list) / total * 100) if total else 0
        phase_stats[ph_id] = {"total": total, "done": len(done_list), "pct": pct, "wos": [w["wo"] for w in ph_all]}
        phase_wos[ph_id] = {"done": done_list, "open": open_list}

    result = dict(plan_data)
    result["milestone_stats"] = milestone_stats
    result["milestone_wos"] = milestone_wos
    result["phase_stats"] = phase_stats
    result["phase_wos"] = phase_wos
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

    wos_result = await _load_wos()
    wos, _ = wos_result
    plan_data = _compute_plan_stats(raw_plan, wos_spec=wos) if raw_plan else None
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


@app.get("/api/thread/{wo}/messages")
async def proxy_thread_messages(wo: str, since: str = ""):
    """Proxy thread messages from the orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            params = {"since": since} if since else {}
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/thread/{wo}/messages", params=params)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        return JSONResponse(content=[], status_code=200)


@app.post("/api/thread/{wo}/messages")
async def proxy_post_thread_message(wo: str, request: Request):
    """Proxy a human-authored message to the orchestrator thread."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body.setdefault("author", "human")
    body.setdefault("role", "human")
    body.setdefault("type", "text")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/thread/{wo}/messages", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Orchestrator unreachable: {e}")


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


@app.get("/settings/agents", response_class=HTMLResponse)
async def settings_agents(request: Request, saved: str = "", error: str = ""):
    cfg = {}
    secrets = {}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            cfg_r, sec_r = await asyncio.gather(
                client.get(f"{ORCHESTRATOR_URL}/api/config"),
                client.get(f"{ORCHESTRATOR_URL}/api/secrets"),
            )
            if cfg_r.status_code == 200:
                cfg = cfg_r.json()
            if sec_r.status_code == 200:
                secrets = sec_r.json()
    except Exception:
        pass
    # Fetch installed backends from the agent runner health check
    installed_backends: dict[str, bool] = {}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/backends")
            if r.status_code == 200:
                data = r.json()
                for b in ("claude", "cursor", "codex", "gemini"):
                    installed_backends[b] = bool(data.get(b, False))
    except Exception:
        pass
    return templates.TemplateResponse(request=request, name="settings_agents.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": 3600,
        "github_repo": GITHUB_REPO,
        "cfg": cfg,
        "saved": saved,
        "error": error,
        "orchestrator_offline": not cfg,
        "anthropic_key_set": secrets.get("ANTHROPIC_API_KEY", False),
        "installed_backends": installed_backends,
    })


@app.post("/settings/agents", response_class=HTMLResponse)
async def settings_agents_save(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    payload = {
        "preferred": str(form.get("preferred", "claude")).strip(),
        "name": str(form.get("name", "factory-agent")).strip(),
        "timeout": int(form.get("timeout", "7200")),
        "force_cross_llm_review": form.get("force_cross_llm_review") == "1",
        "reviewers": {
            "security": str(form.get("reviewer_security", "claude")).strip(),
            "architecture": str(form.get("reviewer_architecture", "claude")).strip(),
            "correctness": str(form.get("reviewer_correctness", "claude")).strip(),
            "performance": str(form.get("reviewer_performance", "claude")).strip(),
        },
    }
    anthropic_key = str(form.get("anthropic_key", "")).strip()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.put(f"{ORCHESTRATOR_URL}/api/config", json=payload)
            if r.status_code != 200:
                return RedirectResponse(url=f"/settings/agents?error=Save+failed+({r.status_code})", status_code=303)
            if anthropic_key:
                await client.put(f"{ORCHESTRATOR_URL}/api/secrets", json={"ANTHROPIC_API_KEY": anthropic_key})
    except Exception:
        return RedirectResponse(url="/settings/agents?error=Orchestrator+unreachable", status_code=303)
    return RedirectResponse(url="/settings/agents?saved=1", status_code=303)


@app.get("/usage", response_class=HTMLResponse)
async def usage_page(request: Request):
    data = {"records": [], "summary": {"per_backend": {}}}
    budget: dict = {}
    orchestrator_offline = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            usage_r, budget_r = await asyncio.gather(
                client.get(f"{ORCHESTRATOR_URL}/api/usage"),
                client.get(f"{ORCHESTRATOR_URL}/api/budget"),
                return_exceptions=True,
            )
            if not isinstance(usage_r, Exception) and usage_r.status_code == 200:
                data = usage_r.json()
            else:
                orchestrator_offline = True
            if not isinstance(budget_r, Exception) and budget_r.status_code == 200:
                budget = budget_r.json()
    except Exception:
        orchestrator_offline = True

    per_backend = data.get("summary", {}).get("per_backend", {})

    def _fmt_duration(secs: float) -> str:
        if secs < 60:
            return f"{int(secs)}s"
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    backend_cards = []
    for backend, stats in per_backend.items():
        runs = stats.get("runs", 0)
        successes = stats.get("successes", 0)
        total_s = stats.get("total_duration_s", 0.0)
        ac = stats.get("ask_calls", 0)
        backend_cards.append({
            "name": backend,
            "runs_all_time": runs,
            "runs_this_week": stats.get("runs_this_week", 0),
            "success_rate": round(successes / runs * 100) if runs else 0,
            "total_duration": _fmt_duration(total_s),
            "estimated_requests": runs + ac,
            "ask_calls": ac,
        })

    return templates.TemplateResponse(request=request, name="usage.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": 300,
        "github_repo": GITHUB_REPO,
        "backend_cards": backend_cards,
        "recent_records": data.get("records", []),
        "orchestrator_offline": orchestrator_offline,
        "budget": budget,
    })


@app.get("/health")
async def health():
    return {"status": "ok", "repo": GITHUB_REPO, "token_set": bool(GITHUB_TOKEN)}


@app.get("/settings/authentication", response_class=HTMLResponse)
async def settings_authentication(request: Request, saved: str = "", error: str = ""):
    secrets: dict = {}
    ntfy_config: dict = {}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            sec_r, ntfy_r = await asyncio.gather(
                client.get(f"{ORCHESTRATOR_URL}/api/secrets"),
                client.get(f"{ORCHESTRATOR_URL}/api/notifications/config"),
                return_exceptions=True,
            )
            if not isinstance(sec_r, Exception) and sec_r.status_code == 200:
                secrets = sec_r.json()
            if not isinstance(ntfy_r, Exception) and ntfy_r.status_code == 200:
                ntfy_config = ntfy_r.json()
    except Exception:
        pass
    ntfy_topic = ntfy_config.get("ntfy_topic", "")
    ntfy_server = ntfy_config.get("ntfy_server", "https://ntfy.sh")
    return templates.TemplateResponse(request=request, name="settings_authentication.html", context={
        "site_title": SITE_TITLE,
        "refresh_seconds": 3600,
        "github_repo": GITHUB_REPO,
        "saved": saved,
        "error": error,
        "github_token_set": bool(GITHUB_TOKEN) or secrets.get("GITHUB_TOKEN", False),
        "anthropic_key_set": secrets.get("ANTHROPIC_API_KEY", False),
        "slack_webhook_set": secrets.get("SLACK_WEBHOOK_URL", False),
        "slack_bot_token_set": secrets.get("SLACK_BOT_TOKEN", False),
        "slack_app_token_set": secrets.get("SLACK_APP_TOKEN", False),
        "ntfy_topic": ntfy_topic,
        "ntfy_server": ntfy_server or "https://ntfy.sh",
        "restart_required": False,
    })


@app.post("/settings/authentication", response_class=HTMLResponse)
async def settings_authentication_save(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    github_token = str(form.get("github_token", "")).strip()
    github_repo = str(form.get("github_repo", "")).strip()
    anthropic_key = str(form.get("anthropic_key", "")).strip()
    slack_webhook = str(form.get("slack_webhook", "")).strip()
    slack_bot_token = str(form.get("slack_bot_token", "")).strip()
    slack_app_token = str(form.get("slack_app_token", "")).strip()

    ntfy_topic = str(form.get("ntfy_topic", "")).strip()
    ntfy_server = str(form.get("ntfy_server", "")).strip()

    secrets_payload: dict = {}
    if github_token:
        secrets_payload["GITHUB_TOKEN"] = github_token
    if anthropic_key:
        secrets_payload["ANTHROPIC_API_KEY"] = anthropic_key
    if slack_webhook:
        secrets_payload["SLACK_WEBHOOK_URL"] = slack_webhook
    if slack_bot_token:
        secrets_payload["SLACK_BOT_TOKEN"] = slack_bot_token
    if slack_app_token:
        secrets_payload["SLACK_APP_TOKEN"] = slack_app_token
    if github_repo:
        secrets_payload["GITHUB_REPO"] = github_repo
    if ntfy_topic:
        secrets_payload["NTFY_TOPIC"] = ntfy_topic
    if ntfy_server:
        secrets_payload["NTFY_SERVER"] = ntfy_server

    if secrets_payload:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.put(f"{ORCHESTRATOR_URL}/api/secrets", json=secrets_payload)
                if r.status_code != 200:
                    return RedirectResponse(
                        url=f"/settings/authentication?error=Save+failed+({r.status_code})",
                        status_code=303,
                    )
        except Exception:
            return RedirectResponse(
                url="/settings/authentication?error=Orchestrator+unreachable",
                status_code=303,
            )

    return RedirectResponse(url="/settings/authentication?saved=1", status_code=303)


# ── Plan Authoring UI (WO-373) ────────────────────────────────────────────────

import github_writer as gw


def _plan_context_base() -> dict:
    plan_data = _load_plan_from_orchestrator() or {}
    return {
        "site_title": SITE_TITLE,
        "github_repo": GITHUB_REPO,
        "refresh_seconds": 3600,
        "phases": plan_data.get("phases", []),
        "milestones": plan_data.get("milestones", []),
        "queue": plan_data.get("queue", []),
    }


@app.get("/settings/plan", response_class=HTMLResponse)
async def settings_plan(request: Request, pr_url: str = "", error: str = ""):
    ctx = _plan_context_base()
    held: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/held-wos")
            if r.status_code == 200:
                held = r.json()
    except Exception:
        pass
    ctx.update({"pr_url": pr_url, "error": error, "pending_validations": [], "held_wos": held})
    return templates.TemplateResponse(request=request, name="settings_plan.html", context=ctx)


@app.post("/settings/plan/wos/{wo_id}/hold", response_class=HTMLResponse)
async def settings_plan_hold_wo(wo_id: str, request: Request):
    from fastapi.responses import RedirectResponse
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{ORCHESTRATOR_URL}/api/wos/{wo_id}/hold")
    except Exception:
        pass
    return RedirectResponse(url="/settings/plan", status_code=303)


@app.post("/settings/plan/wos/{wo_id}/unhold", response_class=HTMLResponse)
async def settings_plan_unhold_wo(wo_id: str, request: Request):
    from fastapi.responses import RedirectResponse
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.request("DELETE", f"{ORCHESTRATOR_URL}/api/wos/{wo_id}/hold")
    except Exception:
        pass
    return RedirectResponse(url="/settings/plan", status_code=303)


@app.get("/settings/plan/wos/{wo_id}/edit", response_class=HTMLResponse)
async def settings_plan_edit_wo_form(wo_id: str, request: Request, error: str = ""):
    content = ""
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            content, _ = await gw.read_wo_file(wo_id, GITHUB_TOKEN, GITHUB_REPO, WO_PATH)
        except Exception as exc:
            error = str(exc)[:200]
    return templates.TemplateResponse(request=request, name="settings_plan_edit_wo.html", context={
        "site_title": SITE_TITLE,
        "github_repo": GITHUB_REPO,
        "refresh_seconds": 3600,
        "wo_id": wo_id,
        "content": content,
        "error": error,
    })


@app.post("/settings/plan/wos/{wo_id}/edit", response_class=HTMLResponse)
async def settings_plan_edit_wo_submit(wo_id: str, request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    content = str(form.get("content", "")).strip()
    if not content:
        return RedirectResponse(url=f"/settings/plan/wos/{wo_id}/edit?error=Content+cannot+be+empty", status_code=303)
    try:
        result = await gw.edit_wo(wo_id, content, GITHUB_TOKEN, GITHUB_REPO, WO_PATH)
        pr_url = result.get("pr_url", "")
        return RedirectResponse(url=f"/settings/plan?pr_url={pr_url}", status_code=303)
    except Exception as exc:
        return RedirectResponse(
            url=f"/settings/plan/wos/{wo_id}/edit?error={str(exc)[:120]}",
            status_code=303,
        )


@app.get("/settings/plan/wos/new", response_class=HTMLResponse)
async def settings_plan_new_wo(request: Request, error: str = ""):
    next_num = 374
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            next_num = await gw.next_wo_number(GITHUB_REPO, WO_PATH, GITHUB_TOKEN)
        except Exception:
            pass

    wos, _ = await _load_wos()
    existing_programs = sorted({s.program for s in wos.values() if s.program})

    plan = _load_plan_from_orchestrator() or {}
    phases = [{"id": p.get("id", ""), "label": p.get("label", p.get("id", ""))} for p in plan.get("phases", [])]
    milestones = [{"id": m.get("id", ""), "label": m.get("label", m.get("id", ""))} for m in plan.get("milestones", [])]

    return templates.TemplateResponse(request=request, name="settings_plan_new_wo.html", context={
        "site_title": SITE_TITLE,
        "github_repo": GITHUB_REPO,
        "refresh_seconds": 3600,
        "next_wo_number": next_num,
        "error": error,
        "description": "",
        "existing_programs": existing_programs,
        "phases": phases,
        "milestones": milestones,
    })


@app.post("/settings/plan/wos/draft", response_class=HTMLResponse)
async def settings_plan_draft_wo(request: Request):
    form = await request.form()
    description = str(form.get("description", "")).strip()
    if not description:
        return RedirectResponse(url="/settings/plan/wos/new?error=Please+describe+what+you+want+to+build", status_code=303)

    next_num = 374
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            next_num = await gw.next_wo_number(GITHUB_REPO, WO_PATH, GITHUB_TOKEN)
        except Exception:
            pass

    backend = str(form.get("backend", "claude-api")).strip() or "claude-api"
    program = str(form.get("program", "")).strip()
    priority = str(form.get("priority", "")).strip()
    phase = str(form.get("phase", "")).strip()
    effort = str(form.get("effort", "")).strip()
    depends_on = str(form.get("depends_on", "")).strip()

    draft = None
    error = ""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{ORCHESTRATOR_URL}/api/plan/draft",
                json={
                    "description": description,
                    "next_wo_num": next_num,
                    "backend": backend,
                    "program": program,
                    "priority": priority,
                    "phase": phase,
                    "effort": effort,
                    "depends_on": depends_on,
                },
            )
            if r.status_code == 200:
                draft = r.json()
            else:
                error = f"Draft failed ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        error = f"Orchestrator unreachable: {e}"

    if error or not draft:
        wos, _ = await _load_wos()
        existing_programs = sorted({s.program for s in wos.values() if s.program})
        plan = _load_plan_from_orchestrator() or {}
        phases = [{"id": p.get("id", ""), "label": p.get("label", p.get("id", ""))} for p in plan.get("phases", [])]
        milestones = [{"id": m.get("id", ""), "label": m.get("label", m.get("id", ""))} for m in plan.get("milestones", [])]
        return templates.TemplateResponse(request=request, name="settings_plan_new_wo.html", context={
            "site_title": SITE_TITLE,
            "github_repo": GITHUB_REPO,
            "refresh_seconds": 3600,
            "next_wo_number": next_num,
            "error": error or "Draft generation failed — try again",
            "description": description,
            "existing_programs": existing_programs,
            "phases": phases,
            "milestones": milestones,
        })

    ac_text = "\n".join(draft.get("acceptance_criteria", []))
    return templates.TemplateResponse(request=request, name="settings_plan_review_wo.html", context={
        "site_title": SITE_TITLE,
        "github_repo": GITHUB_REPO,
        "refresh_seconds": 3600,
        "next_wo_number": next_num,
        "draft": draft,
        "ac_text": ac_text,
        "error": "",
    })


@app.post("/settings/plan/wos", response_class=HTMLResponse)
async def settings_plan_create_wo(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()

    title = str(form.get("title", "")).strip()
    if not title:
        return RedirectResponse(url="/settings/plan/wos/new?error=Title+is+required", status_code=303)

    problem = str(form.get("problem", "")).strip()
    what_to_build = str(form.get("what_to_build", "")).strip()
    if not problem or not what_to_build:
        return RedirectResponse(url="/settings/plan/wos/new?error=Problem+and+What+to+Build+are+required", status_code=303)

    # Accept wo_number (review form) or number (legacy)
    number = int(form.get("wo_number") or form.get("number") or "374")

    criteria_raw = str(form.get("acceptance_criteria", "")).strip()
    criteria = [c.strip() for c in criteria_raw.splitlines() if c.strip()]

    depends_raw = str(form.get("depends_on", "")).strip()
    depends_on = [d.strip() for d in depends_raw.split(",") if d.strip()]

    blocks_multi = form.getlist("blocks_milestones") if hasattr(form, "getlist") else []
    blocks_raw = str(form.get("blocks_milestones", "")).strip()
    blocks = [b.strip() for b in blocks_multi if b.strip()] or [b.strip() for b in blocks_raw.split(",") if b.strip()]

    wo_data = {
        "number": number,
        "title": title,
        "phase": str(form.get("phase", "p2")),
        "priority": str(form.get("priority", "P2")),
        "effort": str(form.get("effort", "M")),
        "services": str(form.get("services", "none")).strip() or "none",
        "depends_on": depends_on,
        "blocks_milestones": blocks,
        "problem": problem,
        "what_to_build": what_to_build,
        "acceptance_criteria": criteria,
        "notes": str(form.get("notes", "")).strip(),
    }

    try:
        result = await gw.create_wo(wo_data, GITHUB_TOKEN, GITHUB_REPO, WO_PATH, PLAN_PATH)
        wo_url = result.get("url", "")
        return RedirectResponse(url=f"/settings/plan?wo_url={wo_url}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/settings/plan/wos/new?error={str(e)[:120]}", status_code=303)


@app.post("/settings/plan/phases", response_class=HTMLResponse)
async def settings_plan_create_phase(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    phase_data = {
        "id": str(form.get("id", "")).strip(),
        "label": str(form.get("label", "")).strip(),
        "target_date": str(form.get("target_date", "")).strip(),
        "milestone": str(form.get("milestone", "")).strip() or None,
        "description": str(form.get("description", "")).strip(),
        "parallel": bool(form.get("parallel")),
    }
    if not phase_data["id"]:
        return RedirectResponse(url="/settings/plan?error=Phase+ID+is+required", status_code=303)
    try:
        result = await gw.add_phase(phase_data, GITHUB_TOKEN, GITHUB_REPO, PLAN_PATH)
        if "error" in result:
            return RedirectResponse(url=f"/settings/plan?error={result['error']}", status_code=303)
        return RedirectResponse(url="/settings/plan?created=phase", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/settings/plan?error={str(e)[:120]}", status_code=303)


@app.post("/settings/plan/milestones", response_class=HTMLResponse)
async def settings_plan_create_milestone(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    milestone_data = {
        "id": str(form.get("id", "")).strip(),
        "label": str(form.get("label", "")).strip(),
        "target_date": str(form.get("target_date", "")).strip(),
        "description": str(form.get("description", "")).strip(),
    }
    if not milestone_data["id"]:
        return RedirectResponse(url="/settings/plan?error=Milestone+ID+is+required", status_code=303)
    try:
        result = await gw.add_milestone(milestone_data, GITHUB_TOKEN, GITHUB_REPO, PLAN_PATH)
        if "error" in result:
            return RedirectResponse(url=f"/settings/plan?error={result['error']}", status_code=303)
        return RedirectResponse(url="/settings/plan?created=milestone", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/settings/plan?error={str(e)[:120]}", status_code=303)


@app.delete("/api/milestones/{milestone_id}")
async def delete_milestone_proxy(milestone_id: str):
    """Proxy DELETE to orchestrator."""
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.delete(f"{ORCHESTRATOR_URL}/api/milestones/{milestone_id}")
        return JSONResponse(content=r.json() if r.content else {}, status_code=r.status_code)


@app.delete("/api/phases/{phase_id}")
async def delete_phase_proxy(phase_id: str):
    """Proxy DELETE to orchestrator."""
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.delete(f"{ORCHESTRATOR_URL}/api/phases/{phase_id}")
        return JSONResponse(content=r.json() if r.content else {}, status_code=r.status_code)



@app.get("/api/backends")
async def api_backends():
    """Proxy to orchestrator /api/backends — tells the UI which agents are available."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/backends")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {
        "claude-api": False,
        "agent_runner_online": False,
        "claude": False,
        "cursor": False,
        "codex": False,
        "gemini": False,
    }


@app.get("/api/plan/next-wo-number")
async def api_next_wo_number():
    """Return the next available WO number."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {"next": 374}
    try:
        next_num = await gw.next_wo_number(GITHUB_REPO, WO_PATH, GITHUB_TOKEN)
        return {"next": next_num}
    except Exception:
        return {"next": 374}


# ── Oryntra CORS proxy ────────────────────────────────────────────────────────
# The Oryntra Chrome extension runs in the browser (different origin from the
# status site). Browsers block cross-origin requests, so Oryntra posts to this
# proxy instead of the orchestrator directly.

@app.post("/api/proxy/thread/{wo}/messages")
async def proxy_thread_post(wo: str, request: Request):
    """CORS-friendly proxy: forward Oryntra annotation to orchestrator thread."""
    body = await request.json()
    if not body.get("author"):
        body["author"] = "human"
    if not body.get("role"):
        body["role"] = "human"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{ORCHESTRATOR_URL}/api/thread/{wo}/messages",
            json=body,
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


@app.get("/api/proxy/thread/{wo}/images/{filename}")
async def proxy_thread_image(wo: str, filename: str):
    """Proxy image served by orchestrator so the browser can load it same-origin."""
    url = f"{ORCHESTRATOR_URL}/api/thread/{wo}/images/{filename}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Image not found")
    return StreamingResponse(
        iter([resp.content]),
        media_type=resp.headers.get("content-type", "image/png"),
    )


# ── Factory Floor ─────────────────────────────────────────────────────────────

def _log_line_matches_wo(line: str, wo_number: str) -> bool:
    """True if a log line is relevant to a specific WO."""
    if not wo_number:
        return True
    return f"WO-{wo_number}" in line


def _log_line_matches_agent(line: str, agent: str) -> bool:
    """True if a log line mentions the given agent backend name (case-insensitive)."""
    if not agent:
        return True
    needle = agent.lower()
    low = line.lower()
    # Exclude noisy health-check lines when filtering by agent
    if "[draft-server]" in line and "GET /health" in line:
        return False
    return needle in low


@app.get("/api/runner/log/stream")
async def stream_runner_log(request: Request, wo: str = "", agent: str = "", tail: int = 150):
    """SSE: proxy the orchestrator's in-memory log stream (avoids Docker volume mount lag)."""
    params: dict = {"tail": tail}
    if agent:
        params["agent"] = agent

    async def event_gen():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                url = f"{ORCHESTRATOR_URL}/api/log/stream"
                async with client.stream("GET", url, params=params) as resp:
                    async for raw in resp.aiter_lines():
                        if await request.is_disconnected():
                            break
                        if not raw:
                            continue
                        if raw.startswith("data:"):
                            try:
                                line = json.loads(raw[5:].strip())
                            except Exception:
                                line = raw[5:].strip()
                            # Apply WO filter here (orchestrator only filters by agent)
                            if wo and not _log_line_matches_wo(line, wo):
                                continue
                            yield f"data: {json.dumps(line)}\n\n"
                        else:
                            yield f"{raw}\n"
        except Exception as e:
            yield f"data: {json.dumps(f'[log stream error: {e}]')}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/anthropic-usage")
async def api_anthropic_usage():
    """Proxy orchestrator Anthropic API usage summary."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/anthropic-usage")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {"records": [], "summary": {"call_count": 0}}


@app.get("/api/budget")
async def api_budget():
    """Proxy orchestrator /api/budget — AI provider token/spend summary."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/budget")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


@app.get("/api/factory/dispatch")
async def api_factory_dispatch():
    """Live dispatch state — which WOs are claimed and what each agent is doing."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/dispatch")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


@app.delete("/api/factory/dispatch/{wo_id}")
async def api_factory_release_wo(wo_id: str):
    """Release a single WO from dispatch state so it can be re-queued."""
    async with httpx.AsyncClient(timeout=4) as client:
        r = await client.delete(f"{ORCHESTRATOR_URL}/api/dispatch/{wo_id}")
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.post("/api/dispatch/{wo_id}/retry")
async def api_factory_retry_wo(wo_id: str):
    """Re-queue a failed WO so the runner picks it up again."""
    async with httpx.AsyncClient(timeout=4) as client:
        r = await client.post(f"{ORCHESTRATOR_URL}/api/dispatch/{wo_id}/retry")
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.delete("/api/factory/dispatch")
async def api_factory_release_all():
    """Clear entire dispatch state."""
    async with httpx.AsyncClient(timeout=4) as client:
        r = await client.delete(f"{ORCHESTRATOR_URL}/api/dispatch")
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.get("/api/factory/pause")
async def api_factory_pause_state():
    async with httpx.AsyncClient(timeout=3) as client:
        r = await client.get(f"{ORCHESTRATOR_URL}/api/factory/pause")
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.post("/api/factory/pause")
async def api_factory_pause():
    async with httpx.AsyncClient(timeout=3) as client:
        r = await client.post(f"{ORCHESTRATOR_URL}/api/factory/pause")
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.post("/api/factory/resume")
async def api_factory_resume():
    async with httpx.AsyncClient(timeout=3) as client:
        r = await client.post(f"{ORCHESTRATOR_URL}/api/factory/resume")
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.post("/api/factory/pm")
async def api_factory_pm(request: Request):
    """PM assistant — proxy to orchestrator /api/pm/chat."""
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}/api/pm/chat", json=body)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"type": "text", "reply": f"PM unavailable: {e}", "wo_draft": None}, status_code=200)


@app.post("/api/factory/wos")
async def api_factory_create_wo(request: Request):
    """Create a WO directly from a draft (used by PM chat inline creation)."""
    body = await request.json()
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return JSONResponse(content={"error": "GitHub not configured"}, status_code=503)
    try:
        if "number" not in body:
            body["number"] = await gw.next_wo_number(GITHUB_REPO, WO_PATH, GITHUB_TOKEN)
        result = await gw.create_wo(body, GITHUB_TOKEN, GITHUB_REPO, WO_PATH, PLAN_PATH)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/api/factory/notifications/test")
async def api_factory_notifications_test():
    """Send a test ntfy notification via orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}/api/notifications/test")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/api/factory/slack/status")
async def api_factory_slack_status():
    """Proxy Slack bot connection status from orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/slack/status")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"connected": False, "error": str(e)}, status_code=503)


@app.post("/api/factory/slack/reconnect")
async def api_factory_slack_reconnect():
    """Trigger Slack bot reconnect via orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}/api/slack/reconnect")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=503)


@app.get("/api/factory/dependabot/prs")
async def api_factory_dependabot_prs():
    """Proxy Dependabot PR list from orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/dependabot/prs")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"prs": [], "error": str(e)}, status_code=503)


@app.post("/api/factory/dependabot/prs/{number}/rebase")
async def api_factory_dependabot_rebase(number: int):
    """Proxy Dependabot rebase action to orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}/api/dependabot/prs/{number}/rebase")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=503)


@app.post("/api/factory/dependabot/prs/{number}/recreate")
async def api_factory_dependabot_recreate(number: int):
    """Proxy Dependabot recreate action to orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}/api/dependabot/prs/{number}/recreate")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=503)


@app.post("/api/factory/dependabot/prs/{number}/approve-merge")
async def api_factory_dependabot_approve_merge(number: int):
    """Proxy Dependabot approve-merge action to orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}/api/dependabot/prs/{number}/approve-merge")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/factory", response_class=HTMLResponse)
async def factory_floor(request: Request):
    backends = {
        "claude-api": False, "agent_runner_online": False,
        "claude": False, "cursor": False, "codex": False, "gemini": False,
        "exhausted_backends": [],
    }
    dispatch: dict = {}
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            b_r, d_r = await asyncio.gather(
                client.get(f"{ORCHESTRATOR_URL}/api/backends"),
                client.get(f"{ORCHESTRATOR_URL}/api/dispatch"),
                return_exceptions=True,
            )
            if not isinstance(b_r, Exception) and b_r.status_code == 200:
                backends.update(b_r.json())
            if not isinstance(d_r, Exception) and d_r.status_code == 200:
                dispatch = d_r.json()
    except Exception:
        pass

    active_wos = sorted(dispatch.values(), key=lambda w: w.get("claimed_at", ""), reverse=True)

    # Map which backend names are actively working WOs so agent cards can show status.
    # Use the `backend` field (set by runner when claiming) for exact matching.
    # Fall back to the `agent` field prefix for old dispatch entries that predate the fix.
    # Exclude "complete" WOs — they don't count as active work.
    backend_wos: dict[str, list] = {}
    for wo in active_wos:
        if wo.get("status") == "complete":
            continue
        b = wo.get("backend") or wo.get("agent", "")
        for backend in ["claude", "cursor", "codex", "gemini"]:
            if b == backend or b.startswith(backend + "-"):
                backend_wos.setdefault(backend, []).append(wo)
                break

    pending_validations = _load_validations()
    pending_validations = [v for v in pending_validations if v.get("status") == "pending"]

    plan = _load_plan_from_orchestrator() or {}
    phases = [{"id": p.get("id", ""), "label": p.get("label", p.get("id", ""))} for p in plan.get("phases", [])]

    return templates.TemplateResponse(request=request, name="factory.html", context={
        "site_title": SITE_TITLE,
        "github_repo": GITHUB_REPO,
        "backends": backends,
        "active_wos": active_wos,
        "backend_wos": backend_wos,
        "refresh_seconds": 9999,
        "pending_validations": pending_validations,
        "phases": phases,
    })
