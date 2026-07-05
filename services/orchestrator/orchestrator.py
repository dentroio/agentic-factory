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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import thread as thread_store
from github_dispatch import trigger_codex_workflow
from notifications import notify_validation_needed
from plan_engine import next_wo, sorted_queue

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
MAX_PARALLEL_WOS = int(os.getenv("MAX_PARALLEL_WOS", "2"))
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")

# Optional: comma-separated secondary repos to include in the WO board.
# Format: "owner/repo" or "owner/repo:docs/work_orders" to override WO path.
# Secondary repos contribute WO specs to the board only — PLAN.json and the
# dispatch queue always come from GITHUB_REPO.
_SECONDARY_REPOS_RAW = [r.strip() for r in os.getenv("SECONDARY_REPOS", "").split(",") if r.strip()]
SECONDARY_REPOS: list[tuple[str, str]] = []
for _entry in _SECONDARY_REPOS_RAW:
    if ":" in _entry:
        _repo, _path = _entry.split(":", 1)
        SECONDARY_REPOS.append((_repo.strip(), _path.strip()))
    else:
        SECONDARY_REPOS.append((_entry, WO_PATH))
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
_held_wos: set[str] = set()            # WO IDs on hold (skip, don't claim)

HOLD_PATH = DATA_DIR / "held_wos.json"


def _load_state() -> None:
    global _dispatch_state, _validations, _held_wos
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
    if HOLD_PATH.exists():
        try:
            _held_wos = set(json.loads(HOLD_PATH.read_text()))
        except Exception:
            _held_wos = set()


def _save_dispatch() -> None:
    DISPATCH_STATE_PATH.write_text(json.dumps(_dispatch_state, indent=2))


def _save_held() -> None:
    HOLD_PATH.write_text(json.dumps(sorted(_held_wos), indent=2))


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
    ci_passed: bool = True
    security_passed: bool = True
    thread_summary: str = ""


class CodexDispatchRequest(BaseModel):
    wo: str
    repo: str = ""
    ref: str = "main"
    slug: str = ""


class ThreadMessage(BaseModel):
    author: str            # "claude-runner", "human", "system", "codex-reviewer"
    role: str              # "agent" | "human" | "reviewer" | "system"
    type: str = "text"     # "text" | "ci_result" | "security_finding" | "review" | "image"
    content: str
    image_data: str = ""   # base64-encoded PNG/JPEG from Oryntra; saved to disk on receipt
    image_url: str = ""    # served URL, set by server after saving image_data
    metadata: dict = {}


class ValidationDecision(BaseModel):
    decided_by: str
    notes: str = ""


# ── FastAPI app + lifespan ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    thread_store.THREADS_DIR.mkdir(parents=True, exist_ok=True)
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
        if wo_id in _held_wos:
            continue
        claim = _dispatch_state.get(wo_id, {})
        if claim.get("status") in active_statuses:
            continue
        return {**wo, "repo": GITHUB_REPO}

    return {"wo": None, "reason": "queue empty or all candidates claimed/blocked"}


@app.get("/api/held-wos")
async def get_held_wos():
    return sorted(_held_wos)


@app.post("/api/wos/{wo_id}/hold")
async def hold_wo(wo_id: str):
    _held_wos.add(wo_id)
    _save_held()
    return {"held": sorted(_held_wos)}


@app.delete("/api/wos/{wo_id}/hold")
async def unhold_wo(wo_id: str):
    _held_wos.discard(wo_id)
    _save_held()
    return {"held": sorted(_held_wos)}


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
    thread_store.append_message(wo_id, thread_store.system_message(
        f"{wo_id} claimed by **{req.agent}** on `{req.workstation or 'unknown'}`"
    ))
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
    """Agent signals it needs human sign-off before committing.

    Rejects with 422 if CI or security gate not met — the agent must fix
    the failures and call /api/validate again with passing results.
    """
    gate_failures = []
    if not req.ci_passed:
        gate_failures.append("CI checks failed")
    if not req.security_passed:
        gate_failures.append("security scan found CRITICAL or HIGH findings")
    if gate_failures:
        raise HTTPException(
            status_code=422,
            detail=f"Quality gate not met: {'; '.join(gate_failures)}",
        )

    if req.wo in _dispatch_state:
        _dispatch_state[req.wo]["status"] = "awaiting_human"
        _save_dispatch()

    _validations.append({
        "wo": req.wo,
        "agent": req.agent,
        "workstation": req.workstation,
        "verify_url": req.verify_url,
        "steps": req.steps,
        "ci_passed": req.ci_passed,
        "security_passed": req.security_passed,
        "thread_summary": req.thread_summary,
        "requested_at": _utcnow(),
        "status": "pending",
    })
    _save_validations()

    # Post system message and agent summary to thread
    ci_badge = "✅ CI passed" if req.ci_passed else "❌ CI failed"
    sec_badge = "✅ Security passed" if req.security_passed else "❌ Security issues found"
    thread_store.append_message(req.wo, thread_store.system_message(
        f"Awaiting human review — {ci_badge} · {sec_badge}",
        metadata={"ci_passed": req.ci_passed, "security_passed": req.security_passed},
    ))
    if req.thread_summary:
        thread_store.append_message(req.wo, thread_store.make_message(
            author=req.agent,
            role="agent",
            msg_type="text",
            content=req.thread_summary,
        ))

    print(f"[orchestrator] {req.wo} awaiting human validation from {req.agent}")

    # Fire-and-forget push notifications (ntfy + Slack)
    asyncio.create_task(notify_validation_needed(
        wo_id=req.wo,
        agent=req.agent,
        verify_url=req.verify_url,
        thread_summary=req.thread_summary,
    ))

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
            thread_store.append_message(wo, thread_store.system_message(
                f"✅ Approved by **{decision.decided_by}**"
                + (f" — {decision.notes}" if decision.notes else "")
            ))
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
            thread_store.append_message(wo, thread_store.system_message(
                f"✗ Rejected by **{decision.decided_by}**"
                + (f"\n\nGuidance: {decision.notes}" if decision.notes else "")
            ))
            print(f"[orchestrator] {wo} rejected by {decision.decided_by}: {decision.notes}")
            return {"ok": True}
    raise HTTPException(status_code=404, detail=f"No pending validation for {wo}")


@app.delete("/api/dispatch/{wo_id}")
async def release_dispatch(wo_id: str):
    """Remove a WO from dispatch state — use when a run failed and needs to be re-queued."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    if wo_id not in _dispatch_state:
        raise HTTPException(status_code=404, detail=f"{wo_id} not in dispatch state")
    del _dispatch_state[wo_id]
    _save_dispatch()
    print(f"[orchestrator] {wo_id} released from dispatch (manual reset)")
    return {"ok": True, "released": wo_id}


@app.delete("/api/dispatch")
async def release_all_dispatch():
    """Clear entire dispatch state — use to reset after a crash or bad run."""
    count = len(_dispatch_state)
    _dispatch_state.clear()
    _save_dispatch()
    print(f"[orchestrator] dispatch state cleared ({count} entries removed)")
    return {"ok": True, "released": count}


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
    thread_store.append_message(wo_id, thread_store.system_message(
        f"✅ WO complete — merged and closed by **{req.agent}**"
    ))
    print(f"[orchestrator] {wo_id} marked complete by {req.agent}")
    return {"ok": True}


# ── Thread API ────────────────────────────────────────────────────────────────

@app.post("/api/thread/{wo}/messages")
async def post_thread_message(wo: str, msg: ThreadMessage):
    """Post a message to a WO's thread (agent or human)."""
    image_url = msg.image_url

    if msg.image_data:
        images_dir = DATA_DIR / "threads" / "images" / wo
        images_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        filename = f"{ts}.png"
        try:
            raw = base64.b64decode(msg.image_data)
            (images_dir / filename).write_bytes(raw)
            image_url = f"/api/thread/{wo}/images/{filename}"
        except Exception as e:
            print(f"[orchestrator] failed to save image for {wo}: {e}")

    stored = thread_store.append_message(wo, thread_store.make_message(
        author=msg.author,
        role=msg.role,
        msg_type=msg.type,
        content=msg.content,
        image_url=image_url,
        metadata=dict(msg.metadata),
    ))
    return stored


@app.get("/api/thread/{wo}/images/{filename}")
async def get_thread_image(wo: str, filename: str):
    """Serve a screenshot image stored by the thread message handler."""
    path = DATA_DIR / "threads" / "images" / wo / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/thread/{wo}/messages")
async def get_thread_messages(wo: str, since: str = ""):
    """Return all messages for a WO, or only those after `since` (message id)."""
    messages = thread_store.load_thread(wo)
    if since:
        messages = [m for m in messages if m.get("id", "") > since]
    return messages


@app.get("/api/thread/{wo}/stream")
async def stream_thread(wo: str, since: str = ""):
    """SSE stream — sends new thread messages as they arrive (2 s poll)."""
    async def generate():
        last_id = since
        try:
            while True:
                messages = thread_store.load_thread(wo)
                new_msgs = [m for m in messages if m.get("id", "") > last_id]
                if new_msgs:
                    last_id = new_msgs[-1]["id"]
                    for msg in new_msgs:
                        yield f"data: {json.dumps(msg)}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(2)
        except (GeneratorExit, asyncio.CancelledError):
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/threads")
async def get_all_threads():
    """Summary of all WO threads: {wo_id: {count, last}}."""
    return thread_store.all_thread_summaries()


@app.post("/api/dispatch-codex")
async def dispatch_codex(req: CodexDispatchRequest):
    """Trigger a cloud Codex run for a WO via GitHub Actions workflow_dispatch.

    Best for P3/docs WOs that don't need a local Docker build.
    The workflow creates a branch, runs Codex, and opens a PR — the orchestrator
    poll loop then detects the branch/PR automatically.
    """
    wo_id = req.wo
    repo = req.repo or GITHUB_REPO
    slug = req.slug or wo_id.lower().replace("wo-", "codex")

    existing = _dispatch_state.get(wo_id, {})
    active_statuses = {"claimed", "in_progress", "awaiting_human", "awaiting_commit"}
    if existing.get("status") in active_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"{wo_id} already claimed by {existing.get('agent')} on {existing.get('workstation', '?')}",
        )

    # Pre-claim so no other agent races in
    _dispatch_state[wo_id] = {
        "wo": wo_id,
        "slug": slug,
        "agent": "codex-gh-actions",
        "workstation": "github-actions",
        "claimed_at": _utcnow(),
        "status": "claimed",
    }
    _save_dispatch()

    ok = await trigger_codex_workflow(repo, wo_id, slug, req.ref)
    if not ok:
        del _dispatch_state[wo_id]
        _save_dispatch()
        raise HTTPException(status_code=502, detail=f"workflow_dispatch failed for {wo_id} on {repo}")

    print(f"[orchestrator] {wo_id} dispatched to GitHub Actions Codex on {repo}")
    return {"ok": True, "wo": wo_id, "repo": repo, "agent": "codex-gh-actions"}


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

async def _fetch_wo_specs(client: httpx.AsyncClient, repo: str = GITHUB_REPO, wo_path: str = WO_PATH) -> dict[int, dict]:
    try:
        items = await _get(client, f"/repos/{repo}/contents/{wo_path}")
        wo_files = [i for i in items if i["name"].endswith(".md") and i["name"].startswith("WO-")]
    except Exception as e:
        print(f"[orchestrator] Failed to list WO files for {repo}: {e}")
        return {}

    specs: dict[int, dict] = {}
    for f in wo_files:
        num = _parse_wo_number(f["name"])
        if not num:
            continue
        try:
            data = await _get(client, f"/repos/{repo}/contents/{f['path']}")
            content = base64.b64decode(data["content"]).decode("utf-8")
            specs[num] = {
                "number": num,
                "repo": repo,
                "title": _parse_title(content, num),
                "status": _parse_status(content),
                "priority": _parse_priority(content),
                "effort": _parse_effort(content),
                "depends_on": _parse_depends_on(content),
            }
        except Exception as e:
            print(f"[orchestrator] Failed to fetch WO-{num} from {repo}: {e}")
    return specs


async def _fetch_active_branches(client: httpx.AsyncClient, repo: str = GITHUB_REPO) -> set[int]:
    try:
        branches = await _get(client, f"/repos/{repo}/branches", {"per_page": 100})
        return {int(m.group(1)) for b in branches if (m := re.match(r"wo/(\d+)-", b["name"]))}
    except Exception:
        return set()


async def _fetch_open_pr_wos(client: httpx.AsyncClient, repo: str = GITHUB_REPO) -> set[int]:
    try:
        prs = await _get(client, f"/repos/{repo}/pulls", {"state": "open", "per_page": 100})
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
        # Primary repo fetches (always)
        primary_specs_task = _fetch_wo_specs(client, GITHUB_REPO, WO_PATH)
        active_branches_task = _fetch_active_branches(client, GITHUB_REPO)
        pr_wos_task = _fetch_open_pr_wos(client, GITHUB_REPO)
        merged_task = _fetch_merged_wo_count_this_week(client)
        plan_task = _fetch_plan(client)

        # Secondary repo fetches (parallel)
        secondary_tasks = [
            _fetch_wo_specs(client, repo, wo_path)
            for repo, wo_path in SECONDARY_REPOS
        ]

        results = await asyncio.gather(
            primary_specs_task,
            active_branches_task,
            pr_wos_task,
            merged_task,
            plan_task,
            *secondary_tasks,
        )

    primary_specs: dict[int, dict] = results[0]
    active_branch_wos: set[int] = results[1]
    pr_wos: set[int] = results[2]
    merged_this_week: int = results[3]
    plan_raw: dict | None = results[4]

    # Merge secondary specs (secondary repos contribute board visibility only)
    specs: dict[int, dict] = dict(primary_specs)
    for sec_specs in results[5:]:
        specs.update(sec_specs)

    # Sets for board summary use all specs; dispatch queue uses primary-repo specs only
    done_wos = {num for num, s in specs.items() if _is_done(s["status"])}
    in_progress_wos = active_branch_wos - pr_wos - done_wos
    in_review_wos = pr_wos - done_wos
    open_wos = {num for num, s in specs.items()
                if not _is_done(s["status"]) and num not in active_branch_wos and num not in pr_wos}
    blocked_wos = {num for num, s in specs.items() if _is_blocked(s["status"])}

    # Plan engine only operates on primary repo WOs
    primary_open_wos = {num for num in open_wos if specs[num].get("repo", GITHUB_REPO) == GITHUB_REPO}

    plan_next: dict | None = None
    plan_queue_sorted: list[dict] = []
    if plan_raw:
        wo_statuses = _build_wo_statuses(primary_specs, active_branch_wos, pr_wos,
                                         {n for n in done_wos if n in primary_specs})
        plan_next = next_wo(plan_raw, wo_statuses)
        plan_queue_sorted = sorted_queue(plan_raw, wo_statuses)

    dispatch_queue, holding_queue, cycle_warnings = _resolve_dependencies(
        {num: s for num, s in specs.items() if num in primary_open_wos}, done_wos,
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


# ── Agent config endpoints ────────────────────────────────────────────────────

AGENT_CONFIG_PATH = DATA_DIR / "agent_config.json"

_DEFAULT_AGENT_CONFIG = {
    "preferred": "claude",
    "name": "factory-agent",
    "timeout": 7200,
    "reviewers": {
        "security": "claude",
        "architecture": "claude",
        "correctness": "claude",
        "performance": "claude",
    },
}


def _load_agent_config() -> dict:
    if not AGENT_CONFIG_PATH.exists():
        return dict(_DEFAULT_AGENT_CONFIG)
    try:
        return {**_DEFAULT_AGENT_CONFIG, **json.loads(AGENT_CONFIG_PATH.read_text())}
    except Exception:
        return dict(_DEFAULT_AGENT_CONFIG)


@app.get("/api/config")
async def get_agent_config():
    return _load_agent_config()


@app.put("/api/config")
async def put_agent_config(request: Request):
    try:
        incoming = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    existing = _load_agent_config()
    if "reviewers" in incoming and isinstance(incoming["reviewers"], dict):
        existing["reviewers"] = {**existing.get("reviewers", {}), **incoming["reviewers"]}
        incoming = {k: v for k, v in incoming.items() if k != "reviewers"}
    merged = {**existing, **incoming}
    AGENT_CONFIG_PATH.write_text(json.dumps(merged, indent=2))
    return merged


# ── Usage tracking endpoints ──────────────────────────────────────────────────

USAGE_PATH = DATA_DIR / "usage.json"


class UsageRecord(BaseModel):
    ts: str
    wo: str
    backend: str
    duration_s: float
    success: bool
    ask_calls: list[dict] = []


def _load_usage() -> list[dict]:
    if not USAGE_PATH.exists():
        return []
    try:
        return json.loads(USAGE_PATH.read_text())
    except Exception:
        return []


@app.post("/api/usage")
async def post_usage(record: UsageRecord):
    records = _load_usage()
    records.append(record.model_dump())
    if len(records) > 500:
        records = records[-500:]
    USAGE_PATH.write_text(json.dumps(records, indent=2))
    return {"ok": True}


@app.get("/api/usage")
async def get_usage():
    records = _load_usage()
    from datetime import timedelta
    week_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    per_backend: dict[str, dict] = {}
    for r in records:
        b = r.get("backend", "unknown")
        if b not in per_backend:
            per_backend[b] = {"runs": 0, "successes": 0, "total_duration_s": 0.0, "ask_calls": 0, "runs_this_week": 0}
        per_backend[b]["runs"] += 1
        if r.get("success"):
            per_backend[b]["successes"] += 1
        per_backend[b]["total_duration_s"] += r.get("duration_s", 0.0)
        per_backend[b]["ask_calls"] += len(r.get("ask_calls", []))
        if r.get("ts", "") >= week_ago:
            per_backend[b]["runs_this_week"] += 1
    return {"records": records[-20:], "summary": {"per_backend": per_backend}}


# ── Secrets storage (persisted to data volume, editable from settings UI) ─────

SECRETS_PATH = DATA_DIR / "secrets.json"


def _load_secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    try:
        return json.loads(SECRETS_PATH.read_text())
    except Exception:
        return {}


@app.get("/api/secrets")
async def get_secrets():
    """Return which secret keys are set — never their values."""
    return {k: bool(v) for k, v in _load_secrets().items()}


@app.put("/api/secrets")
async def put_secrets(request: Request):
    try:
        incoming = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    secrets = _load_secrets()
    for k, v in incoming.items():
        if v:
            secrets[k] = str(v)
        elif k in secrets:
            del secrets[k]
    SECRETS_PATH.write_text(json.dumps(secrets, indent=2))
    return {k: bool(v) for k, v in secrets.items()}


# ── WO Draft generation ────────────────────────────────────────────────────────

AGENT_RUNNER_URL = os.getenv("AGENT_RUNNER_URL", "http://host.docker.internal:8101")


def _get_anthropic_key() -> str:
    """Read ANTHROPIC_API_KEY from env first, then secrets volume (set via UI)."""
    return os.getenv("ANTHROPIC_API_KEY") or _load_secrets().get("ANTHROPIC_API_KEY", "")

_DRAFT_SYSTEM = (
    "You are a software engineering planning agent. Convert a plain-English feature request "
    "into a structured Work Order spec.\n\n"
    "Return ONLY valid JSON (no markdown fences, no preamble) with these exact keys:\n"
    "- title: short action-oriented title (max 60 chars)\n"
    "- priority: 'P1', 'P2', or 'P3'\n"
    "- effort: 'XS', 'S', 'M', 'L', or 'XL'\n"
    "- services: comma-separated service names affected (e.g. 'orchestrator, status-site')\n"
    "- problem: 2-4 sentences describing the pain point\n"
    "- what_to_build: technical description with specific files and approach\n"
    "- acceptance_criteria: array of 3-6 verifiable checklist items\n"
    "- notes: any constraints or context (empty string if none)\n\n"
    "Risk tiers: P1=core/schema changes (human merge required), "
    "P2=additive features/UI (auto-merge allowed), P3=docs only (direct to main).\n"
    "Effort: XS<1h | S~2h | M=half day | L=full day | XL=2-3 days"
)


class DraftRequest(BaseModel):
    description: str
    next_wo_num: int = 1
    backend: str = "claude-api"


@app.get("/api/backends")
async def get_backends():
    """Report which AI backends are available (API key set / CLI installed)."""
    result: dict[str, bool | str] = {
        "claude-api": bool(_get_anthropic_key()),
        "agent_runner_online": False,
        "claude": False,
        "cursor": False,
        "codex": False,
        "gemini": False,
    }
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{AGENT_RUNNER_URL}/health")
            if r.status_code == 200:
                data = r.json()
                result["agent_runner_online"] = True
                for b in ("claude", "cursor", "codex", "gemini"):
                    result[b] = data.get("backends", {}).get(b, False)
    except Exception:
        pass
    return result


@app.post("/api/plan/draft")
async def plan_draft(req: DraftRequest):
    backend = req.backend or "claude-api"

    if backend == "claude-api":
        api_key = _get_anthropic_key()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="Anthropic API key not configured. Add it in Settings → Agents, or select a CLI backend.",
            )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=_DRAFT_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": f"WO number: {req.next_wo_num:03d}\n\nRequest:\n{req.description}",
                }],
            )
            text = msg.content[0].text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)
            data = json.loads(text)
            return data
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {e}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # CLI backend — proxy to agent-runner draft server (runs on host)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{AGENT_RUNNER_URL}/api/draft",
                json={"description": req.description, "next_wo_num": req.next_wo_num, "backend": backend},
            )
            if r.status_code == 200:
                return r.json()
            raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Agent runner not reachable. Start it with: make agent-once  (or make agent-install for the daemon)",
        )


if __name__ == "__main__":
    uvicorn.run("orchestrator:app", host="0.0.0.0", port=API_PORT, log_level="info")
