import asyncio
import base64
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from plan_engine import next_wo, sorted_queue

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
MAX_PARALLEL_WOS = int(os.getenv("MAX_PARALLEL_WOS", "2"))
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
RUNS_PATH = os.getenv("RUNS_PATH", "docs/factory/runs")
PLAN_PATH = os.getenv("PLAN_PATH", "docs/factory/PLAN.json")
DAILY_SUMMARY_HOUR = os.getenv("DAILY_SUMMARY_HOUR", "")
SUMMARY_ISSUE_NUMBER = os.getenv("SUMMARY_ISSUE_NUMBER", "")
API_PORT = int(os.getenv("API_PORT", "8100"))

DATA_DIR = Path("/data")
OUTPUT_PATH = DATA_DIR / "orchestrator.json"
DISPATCH_STATE_PATH = DATA_DIR / "dispatch_state.json"
VALIDATIONS_PATH = DATA_DIR / "pending_validations.json"
WATCHDOG_PATH = Path(os.getenv("WATCHDOG_PATH", "/watchdog/watchdog.json"))

_last_summary_day: int = -1

# ── In-memory state (persisted to volume) ────────────────────────────────────

_dispatch_state: dict[str, dict] = {}   # wo_id → claim record
_validations: list[dict] = []           # pending human validations
_orchestrator_output: dict = {}         # last poll snapshot


def _load_state() -> None:
    global _dispatch_state, _validations
    if DISPATCH_STATE_PATH.exists():
        try:
            _dispatch_state = json.loads(DISPATCH_STATE_PATH.read_text())
        except Exception:
            _dispatch_state = {}
    if VALIDATIONS_PATH.exists():
        try:
            _validations = json.loads(VALIDATIONS_PATH.read_text())
        except Exception:
            _validations = []


def _save_dispatch() -> None:
    DISPATCH_STATE_PATH.write_text(json.dumps(_dispatch_state, indent=2))


def _save_validations() -> None:
    VALIDATIONS_PATH.write_text(json.dumps(_validations, indent=2))


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ── Pydantic models ───────────────────────────────────────────────────────────

class ClaimRequest(BaseModel):
    wo: str           # e.g. "WO-359"
    agent: str        # "claude", "cursor", "antigravity"
    workstation: str = ""
    slug: str = ""


class CompleteRequest(BaseModel):
    wo: str
    agent: str = ""


class ValidateRequest(BaseModel):
    wo: str
    agent: str
    workstation: str = ""
    verify_url: str = ""
    steps: list[str] = []


class ValidationDecision(BaseModel):
    decided_by: str
    notes: str = ""


# ── FastAPI app + lifespan ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _load_state()

    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[orchestrator] WARNING: GITHUB_TOKEN or GITHUB_REPO not set — poll loop disabled")
    else:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(poll, "interval", seconds=POLL_INTERVAL)
        scheduler.start()
        app.state.scheduler = scheduler
        # Fire first poll in background — store ref so it isn't GC'd
        app.state.initial_poll = asyncio.create_task(poll())

    yield

    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown()


app = FastAPI(title="Factory Orchestrator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "repo": GITHUB_REPO}


@app.get("/api/status")
async def get_status():
    return _orchestrator_output


@app.get("/api/next")
async def get_next():
    """Return the highest-priority unclaimed WO, or null if none available."""
    plan = _orchestrator_output.get("plan", {})
    queue: list[dict] = plan.get("queue", [])

    active_statuses = {"claimed", "in_progress", "awaiting_human", "awaiting_commit"}

    for wo in queue:
        wo_id = wo.get("wo", "")
        claim = _dispatch_state.get(wo_id, {})
        if claim.get("status") in active_statuses:
            continue
        return {**wo, "repo": GITHUB_REPO}

    return {"wo": None, "reason": "queue empty or all candidates claimed/blocked"}


@app.post("/api/claim")
async def claim_wo(req: ClaimRequest):
    """Atomically claim a WO. Returns 409 if already claimed by another agent."""
    wo_id = req.wo
    existing = _dispatch_state.get(wo_id, {})
    active_statuses = {"claimed", "in_progress", "awaiting_human", "awaiting_commit"}

    if existing.get("status") in active_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"{wo_id} already claimed by {existing['agent']} on {existing.get('workstation', '?')}",
        )

    _dispatch_state[wo_id] = {
        "wo": wo_id,
        "slug": req.slug,
        "agent": req.agent,
        "workstation": req.workstation,
        "claimed_at": _utcnow(),
        "status": "claimed",
    }
    _save_dispatch()
    print(f"[orchestrator] {wo_id} claimed by {req.agent} on {req.workstation}")
    return {"ok": True, "wo": wo_id, "agent": req.agent}


@app.post("/api/checkin")
async def checkin(wo: str, agent: str, step: str = ""):
    """Agent heartbeat — update step label while working."""
    if wo not in _dispatch_state:
        raise HTTPException(status_code=404, detail=f"{wo} not claimed")
    _dispatch_state[wo]["status"] = "in_progress"
    _dispatch_state[wo]["step"] = step
    _dispatch_state[wo]["last_seen"] = _utcnow()
    _save_dispatch()
    return {"ok": True}


@app.post("/api/validate")
async def request_validation(req: ValidateRequest):
    """Agent signals it needs human sign-off before committing."""
    if req.wo in _dispatch_state:
        _dispatch_state[req.wo]["status"] = "awaiting_human"
        _save_dispatch()

    _validations.append({
        "wo": req.wo,
        "agent": req.agent,
        "workstation": req.workstation,
        "verify_url": req.verify_url,
        "steps": req.steps,
        "requested_at": _utcnow(),
        "status": "pending",
    })
    _save_validations()
    print(f"[orchestrator] {req.wo} awaiting human validation from {req.agent}")
    return {"ok": True}


@app.get("/api/validations")
async def get_validations():
    """Status site polls this to show the validation queue."""
    return _validations


@app.post("/api/validations/{wo}/approve")
async def approve_validation(wo: str, decision: ValidationDecision):
    for v in _validations:
        if v["wo"] == wo and v["status"] == "pending":
            v["status"] = "approved"
            v["decided_by"] = decision.decided_by
            v["decided_at"] = _utcnow()
            v["notes"] = decision.notes
            _save_validations()
            if wo in _dispatch_state:
                _dispatch_state[wo]["status"] = "awaiting_commit"
                _save_dispatch()
            print(f"[orchestrator] {wo} approved by {decision.decided_by}")
            return {"ok": True}
    raise HTTPException(status_code=404, detail=f"No pending validation for {wo}")


@app.post("/api/validations/{wo}/reject")
async def reject_validation(wo: str, decision: ValidationDecision):
    for v in _validations:
        if v["wo"] == wo and v["status"] == "pending":
            v["status"] = "rejected"
            v["decided_by"] = decision.decided_by
            v["decided_at"] = _utcnow()
            v["notes"] = decision.notes
            _save_validations()
            if wo in _dispatch_state:
                _dispatch_state[wo]["status"] = "rejected"
                _save_dispatch()
            print(f"[orchestrator] {wo} rejected by {decision.decided_by}: {decision.notes}")
            return {"ok": True}
    raise HTTPException(status_code=404, detail=f"No pending validation for {wo}")


@app.post("/api/complete")
async def complete_wo(req: CompleteRequest):
    """Agent signals WO is merged and done."""
    wo_id = req.wo
    if wo_id not in _dispatch_state:
        raise HTTPException(status_code=404, detail=f"{wo_id} not in dispatch state")
    _dispatch_state[wo_id]["status"] = "complete"
    _dispatch_state[wo_id]["completed_at"] = _utcnow()
    _save_dispatch()
    # Remove from pending validations
    global _validations
    _validations = [v for v in _validations if v["wo"] != wo_id]
    _save_validations()
    print(f"[orchestrator] {wo_id} marked complete by {req.agent}")
    return {"ok": True}


@app.get("/api/dispatch")
async def get_dispatch():
    """Full dispatch state — which agent owns which WO."""
    return _dispatch_state


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None):
    url = f"https://api.github.com{path}"
    resp = await client.get(url, headers=_headers(), params=params or {})
    resp.raise_for_status()
    return resp.json()


# ── WO spec parsing ───────────────────────────────────────────────────────────

def _parse_wo_number(filename: str) -> int | None:
    m = re.match(r"WO-(\d+)", filename)
    return int(m.group(1)) if m else None


def _parse_status(content: str) -> str:
    m = re.search(r"\*\*Status:\*\*\s*(.+)", content)
    return m.group(1).strip() if m else "Open"


def _parse_priority(content: str) -> str:
    m = re.search(r"\*\*Priority:\*\*\s*(.+)", content)
    return m.group(1).strip() if m else "P3"


def _parse_title(content: str, number: int) -> str:
    m = re.search(r"^# (?:WO-[\d–-]+|Work Order \d+)\s*[—:]\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else f"WO-{number}"


def _parse_effort(content: str) -> str:
    m = re.search(r"\*\*Estimated effort:\*\*\s*(.+)", content)
    return m.group(1).strip() if m else ""


def _parse_depends_on(content: str) -> list[int]:
    m = re.search(r"\*\*Depends on:\*\*\s*(.+)", content)
    if not m:
        return []
    return [int(n) for n in re.findall(r"WO-(\d+)", m.group(1))]


def _is_done(status: str) -> bool:
    s = status.lower()
    return "done" in s or "complete" in s or "✅" in status or "deferred" in s or "superseded" in s or "abandoned" in s


def _is_blocked(status: str) -> bool:
    s = status.lower()
    return "blocked" in s or "🔴" in s


# ── GitHub data fetchers ──────────────────────────────────────────────────────

async def _fetch_wo_specs(client: httpx.AsyncClient) -> dict[int, dict]:
    try:
        items = await _get(client, f"/repos/{GITHUB_REPO}/contents/{WO_PATH}")
        wo_files = [i for i in items if i["name"].endswith(".md") and i["name"].startswith("WO-")]
    except Exception as e:
        print(f"[orchestrator] Failed to list WO files: {e}")
        return {}

    specs: dict[int, dict] = {}
    for f in wo_files:
        num = _parse_wo_number(f["name"])
        if not num:
            continue
        try:
            data = await _get(client, f"/repos/{GITHUB_REPO}/contents/{f['path']}")
            content = base64.b64decode(data["content"]).decode("utf-8")
            specs[num] = {
                "number": num,
                "title": _parse_title(content, num),
                "status": _parse_status(content),
                "priority": _parse_priority(content),
                "effort": _parse_effort(content),
                "depends_on": _parse_depends_on(content),
            }
        except Exception as e:
            print(f"[orchestrator] Failed to fetch WO-{num}: {e}")
    return specs


async def _fetch_active_branches(client: httpx.AsyncClient) -> set[int]:
    try:
        branches = await _get(client, f"/repos/{GITHUB_REPO}/branches", {"per_page": 100})
        return {int(m.group(1)) for b in branches if (m := re.match(r"wo/(\d+)-", b["name"]))}
    except Exception:
        return set()


async def _fetch_open_pr_wos(client: httpx.AsyncClient) -> set[int]:
    try:
        prs = await _get(client, f"/repos/{GITHUB_REPO}/pulls", {"state": "open", "per_page": 100})
        return {int(m.group(1)) for p in prs if (m := re.search(r"WO-(\d+)", p.get("title", "")))}
    except Exception:
        return set()


async def _fetch_merged_wo_count_this_week(client: httpx.AsyncClient) -> int:
    from datetime import timedelta
    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        prs = await _get(client, f"/repos/{GITHUB_REPO}/pulls",
                         {"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"})
        return sum(1 for p in prs if p.get("merged_at") and p["merged_at"] >= since)
    except Exception:
        return 0


async def _fetch_plan(client: httpx.AsyncClient) -> dict | None:
    try:
        data = await _get(client, f"/repos/{GITHUB_REPO}/contents/{PLAN_PATH}")
        return json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    except Exception as e:
        print(f"[orchestrator] Failed to fetch PLAN.json: {e}")
        return None


def _build_wo_statuses(specs: dict[int, dict], active_branch_wos: set[int],
                       pr_wos: set[int], done_wos: set[int]) -> dict[str, str]:
    result: dict[str, str] = {}
    for num, spec in specs.items():
        wo_id = f"WO-{num}"
        if num in done_wos:
            result[wo_id] = "done"
        elif num in pr_wos:
            result[wo_id] = "review"
        elif num in active_branch_wos:
            result[wo_id] = "in_progress"
        else:
            result[wo_id] = spec.get("status", "open")
    return result


def _resolve_dependencies(specs: dict[int, dict], done_wos: set[int]) -> tuple[list[dict], list[dict], list[str]]:
    dispatch: list[dict] = []
    holding: list[dict] = []
    warnings: list[str] = []

    def has_cycle(num: int, visiting: set[int]) -> bool:
        if num in visiting:
            return True
        deps = specs.get(num, {}).get("depends_on", [])
        return any(has_cycle(d, visiting | {num}) for d in deps if d in specs)

    for num, spec in sorted(specs.items(), key=lambda x: (x[1]["priority"], x[0])):
        if _is_done(spec["status"]):
            continue
        if has_cycle(num, set()):
            warnings.append(f"WO-{num} has a circular dependency — skipping")
            continue
        unmet = [d for d in spec.get("depends_on", []) if d not in done_wos]
        if unmet:
            holding.append({
                "wo": num, "title": spec["title"], "priority": spec["priority"],
                "dependencies_met": False, "blocked_by": unmet,
                "reason": f"Waiting on WO-{', WO-'.join(str(d) for d in unmet)}",
            })
        else:
            dispatch.append({
                "wo": num, "title": spec["title"], "priority": spec["priority"],
                "effort": spec["effort"], "dependencies_met": True,
                "recommended_action": "start",
                "reason": "Open, dependencies met" if spec.get("depends_on") else "Open, no dependencies",
            })

    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    dispatch.sort(key=lambda x: (priority_order.get(x["priority"], 9), x["wo"]))
    return dispatch[:MAX_PARALLEL_WOS * 3], holding, warnings


# ── Daily summary ─────────────────────────────────────────────────────────────

async def _maybe_post_summary(client: httpx.AsyncClient, output: dict) -> None:
    global _last_summary_day
    if not DAILY_SUMMARY_HOUR or not SUMMARY_ISSUE_NUMBER:
        return
    now = datetime.now(UTC)
    if now.hour != int(DAILY_SUMMARY_HOUR) or now.day == _last_summary_day:
        return

    board = output["board_summary"]
    lines = [
        f"## Factory Daily Summary — {now.strftime('%a %b %d, %Y')}",
        "",
        f"**Board:** {board['open']} Open · {board['in_progress']} In Progress · "
        f"{board['in_review']} In Review · {board['blocked']} Blocked · {board['done_this_week']} done this week",
        "",
    ]
    for item in output.get("dispatch_queue", [])[:5]:
        lines.append(f"- WO-{item['wo']} ({item['priority']}): {item['title']}")
    body = "\n".join(lines)

    try:
        comments = await _get(client, f"/repos/{GITHUB_REPO}/issues/{SUMMARY_ISSUE_NUMBER}/comments",
                              {"per_page": 100})
        existing = next((c for c in comments if "Factory Daily Summary" in c.get("body", "")), None)
        if existing:
            await client.patch(
                f"https://api.github.com/repos/{GITHUB_REPO}/issues/comments/{existing['id']}",
                headers=_headers(), json={"body": body},
            )
        else:
            await client.post(
                f"https://api.github.com/repos/{GITHUB_REPO}/issues/{SUMMARY_ISSUE_NUMBER}/comments",
                headers=_headers(), json={"body": body},
            )
        _last_summary_day = now.day
    except Exception as e:
        print(f"[orchestrator] Failed to post summary: {e}")


def _load_watchdog() -> dict | None:
    if not WATCHDOG_PATH.exists():
        return None
    try:
        return json.loads(WATCHDOG_PATH.read_text())
    except Exception:
        return None


# ── Main poll loop ────────────────────────────────────────────────────────────

async def poll() -> None:
    global _orchestrator_output
    now_str = _utcnow()

    async with httpx.AsyncClient(timeout=20) as client:
        specs, active_branch_wos, pr_wos, merged_this_week, plan_raw = await asyncio.gather(
            _fetch_wo_specs(client),
            _fetch_active_branches(client),
            _fetch_open_pr_wos(client),
            _fetch_merged_wo_count_this_week(client),
            _fetch_plan(client),
        )

    done_wos = {num for num, s in specs.items() if _is_done(s["status"])}
    in_progress_wos = active_branch_wos - pr_wos - done_wos
    in_review_wos = pr_wos - done_wos
    open_wos = {num for num, s in specs.items()
                if not _is_done(s["status"]) and num not in active_branch_wos and num not in pr_wos}
    blocked_wos = {num for num, s in specs.items() if _is_blocked(s["status"])}

    plan_next: dict | None = None
    plan_queue_sorted: list[dict] = []
    if plan_raw:
        wo_statuses = _build_wo_statuses(specs, active_branch_wos, pr_wos, done_wos)
        plan_next = next_wo(plan_raw, wo_statuses)
        plan_queue_sorted = sorted_queue(plan_raw, wo_statuses)

    dispatch_queue, holding_queue, cycle_warnings = _resolve_dependencies(
        {num: s for num, s in specs.items() if num in open_wos}, done_wos,
    )

    # Enrich active_work with dispatch state (agent/step from API claims)
    active_work = []
    for num in sorted(in_progress_wos | in_review_wos):
        spec = specs.get(num, {})
        wo_id = f"WO-{num}"
        claim = _dispatch_state.get(wo_id, {})
        active_work.append({
            "wo": num,
            "title": spec.get("title", f"WO-{num}"),
            "branch": f"wo/{num}-*" if num in in_progress_wos else None,
            "pr": num in in_review_wos,
            "agent": claim.get("agent"),
            "workstation": claim.get("workstation"),
            "step": claim.get("step"),
            "status": claim.get("status"),
        })

    watchdog = _load_watchdog()
    recommendations: list[str] = []
    if dispatch_queue:
        top = dispatch_queue[0]
        recommendations.append(f"WO-{top['wo']} ({top['priority']}) is ready to start: {top['title']}")
    if watchdog:
        errors = watchdog.get("summary", {}).get("errors", 0)
        if errors:
            recommendations.append(f"{errors} PR(s) have errors — check the CI View")
        runners_busy = watchdog.get("summary", {}).get("runners_busy", 0)
        runners_online = watchdog.get("summary", {}).get("runners_online", 0)
        if runners_online > 0 and runners_busy >= runners_online:
            recommendations.append("All runners busy — hold off starting new WOs")
    if len(in_progress_wos) >= MAX_PARALLEL_WOS:
        recommendations.append(f"At parallel WO limit ({MAX_PARALLEL_WOS})")
    recommendations.extend(cycle_warnings)

    # Pending validations count for status site banner
    pending_validations = [v for v in _validations if v.get("status") == "pending"]

    _orchestrator_output = {
        "generated_at": now_str,
        "poll_interval_seconds": POLL_INTERVAL,
        "max_parallel_wos": MAX_PARALLEL_WOS,
        "pending_validations": len(pending_validations),
        "plan": {
            "loaded": plan_raw is not None,
            "last_updated": plan_raw.get("last_updated") if plan_raw else None,
            "next": plan_next,
            "queue": plan_queue_sorted,
            "all_wos": plan_raw.get("queue", []) if plan_raw else [],
            "deferred": plan_raw.get("deferred", []) if plan_raw else [],
            "milestones": plan_raw.get("milestones", []) if plan_raw else [],
            "phases": plan_raw.get("phases", []) if plan_raw else [],
        },
        "runner_capacity": {
            "total": watchdog.get("summary", {}).get("runners_online", 0) if watchdog else 0,
            "busy": watchdog.get("summary", {}).get("runners_busy", 0) if watchdog else 0,
            "available": max(0, (watchdog.get("summary", {}).get("runners_online", 0) or 0) -
                           (watchdog.get("summary", {}).get("runners_busy", 0) or 0)) if watchdog else 0,
        },
        "board_summary": {
            "total": len(specs),
            "open": len(open_wos),
            "in_progress": len(in_progress_wos),
            "in_review": len(in_review_wos),
            "blocked": len(blocked_wos),
            "done": len(done_wos),
            "done_this_week": merged_this_week,
        },
        "dispatch_queue": dispatch_queue,
        "holding_queue": holding_queue,
        "active_work": active_work,
        "recommendations": recommendations,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(_orchestrator_output, indent=2))
    print(f"[orchestrator] {now_str} — {len(specs)} WOs, {len(dispatch_queue)} dispatchable, "
          f"{len(in_progress_wos)} in-progress, {len(pending_validations)} awaiting validation")

    async with httpx.AsyncClient(timeout=20) as client:
        await _maybe_post_summary(client, _orchestrator_output)


if __name__ == "__main__":
    uvicorn.run("orchestrator:app", host="0.0.0.0", port=API_PORT, log_level="info")
