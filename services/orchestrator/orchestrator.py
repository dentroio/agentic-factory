import asyncio
import base64
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import thread as thread_store
from github_dispatch import trigger_codex_workflow
from slack_bot import start_slack_bot, stop_slack_bot, is_connected as slack_is_connected
from notifications import (
    notify_validation_needed,
    notify_wo_complete,
    notify_wo_error,
    notify_dependabot,
    notify_test,
    notify_factory_alert,
)
from plan_engine import next_wo, sorted_queue

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
CLAIM_TIMEOUT_SECONDS = int(os.getenv("CLAIM_TIMEOUT_SECONDS", "600"))
MAX_PARALLEL_WOS = int(os.getenv("MAX_PARALLEL_WOS", "2"))
REQUIRE_APPROVAL_FOR: set[str] = {p.strip() for p in os.getenv("REQUIRE_APPROVAL_FOR", "P1").split(",") if p.strip()}
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
SPEC_MIN_BODY_LENGTH = int(os.getenv("SPEC_MIN_BODY_LENGTH", "300"))
SPEC_REQUIRED_SECTIONS = ["## Background", "## What to Build", "## Acceptance Criteria"]
SPEC_MIN_AC_ITEMS = int(os.getenv("SPEC_MIN_AC_ITEMS", "3"))

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
# When set, WO specs / PLAN.json / branches are read from the local filesystem
# instead of GitHub API — dramatically reduces API call volume.
LOCAL_REPO_MOUNT = os.getenv("LOCAL_REPO_MOUNT", "")
DAILY_SUMMARY_HOUR = os.getenv("DAILY_SUMMARY_HOUR", "")
SUMMARY_ISSUE_NUMBER = os.getenv("SUMMARY_ISSUE_NUMBER", "")
API_PORT = int(os.getenv("API_PORT", "8100"))

DATA_DIR = Path("/data")
OUTPUT_PATH = DATA_DIR / "orchestrator.json"
DISPATCH_STATE_PATH = DATA_DIR / "dispatch_state.json"
VALIDATIONS_PATH = DATA_DIR / "pending_validations.json"
WATCHDOG_PATH = Path(os.getenv("WATCHDOG_PATH", "/watchdog/watchdog.json"))
DB_PATH = DATA_DIR / "factory.db"

_last_summary_day: int = -1

# ── In-memory state (persisted to volume) ────────────────────────────────────

_dispatch_state: dict[str, dict] = {}   # wo_id → claim record
_validations: list[dict] = []           # pending human validations
_orchestrator_output: dict = {}         # last poll snapshot
_held_wos: set[str] = set()            # WO IDs on hold (skip, don't claim)
_specs_cache: dict[int, dict] = {}     # all merged WO specs from last poll (primary + secondary)
_pm_dispatch: dict | None = None       # PM-requested direct dispatch {wo, backend, title}
_plan_overlay: list[dict] = []         # spec-file WOs not in PLAN.json — runtime-only, never written to disk
_approval_skips: dict[str, str] = {}   # wo_id → ISO timestamp until approval is bypassed

HOLD_PATH = DATA_DIR / "held_wos.json"
PAUSE_PATH = DATA_DIR / "factory_paused.json"
PM_MEMORY_PATH = DATA_DIR / "pm_memory.json"

_pm_memory: dict = {}   # persisted PM preferences, decisions, dispatched history

_factory_paused: bool = False   # when True, get_next() returns null — drains gracefully

# ── In-memory log buffer (replaces file-tail SSE — Docker volume mount lag) ───
_LOG_BUFFER_MAX = 2000
_log_buffer: list[str] = []            # circular buffer of log lines
_log_subscribers: list[asyncio.Queue] = []  # one Queue per active SSE client


def _load_state() -> None:
    global _dispatch_state, _validations, _held_wos, _factory_paused
    _init_db()
    _migrate_plan_json_to_db()
    # Load dispatch state: SQLite primary, JSON fallback (migration path)
    db_runs = _db_load_all_runs()
    if db_runs:
        _dispatch_state = db_runs
        print(f"[orchestrator] loaded {len(db_runs)} dispatch entries from SQLite")
    elif DISPATCH_STATE_PATH.exists():
        try:
            _dispatch_state = json.loads(DISPATCH_STATE_PATH.read_text())
            _db_sync_dispatch()
            print(f"[orchestrator] migrated {len(_dispatch_state)} dispatch entries JSON → SQLite")
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
    if PAUSE_PATH.exists():
        try:
            _factory_paused = json.loads(PAUSE_PATH.read_text()).get("paused", False)
        except Exception:
            _factory_paused = False


def _load_pm_memory() -> None:
    global _pm_memory
    if PM_MEMORY_PATH.exists():
        try:
            _pm_memory = json.loads(PM_MEMORY_PATH.read_text())
        except Exception:
            _pm_memory = {}


def _save_pm_memory() -> None:
    try:
        PM_MEMORY_PATH.write_text(json.dumps(_pm_memory, indent=2))
    except Exception as e:
        print(f"[orchestrator] pm_memory save failed: {e}")


def _pm_memory_summary() -> str:
    """Compact ≤10-line summary of PM memory for injection into system prompt."""
    if not _pm_memory:
        return ""
    lines: list[str] = []
    prefs = _pm_memory.get("preferences", {})
    if prefs.get("preferred_backend"):
        lines.append(f"Preferred backend: {prefs['preferred_backend']}")
    dispatched = _pm_memory.get("dispatched", [])
    if dispatched:
        recent = dispatched[-5:]
        lines.append("Recently dispatched:")
        for d in reversed(recent):
            outcome = f" ({d['outcome']})" if d.get("outcome") else ""
            lines.append(f"  {d['wo']} via {d['backend']} on {d['date']}{outcome}")
    decisions = _pm_memory.get("recent_decisions", [])
    if decisions:
        lines.append("Recent decisions:")
        for dec in decisions[-3:]:
            lines.append(f"  {dec['decision']}")
    return "\n".join(lines[:10])


def _save_dispatch() -> None:
    # JSON backup for other processes that may read the volume directly
    try:
        DISPATCH_STATE_PATH.write_text(json.dumps(_dispatch_state, indent=2))
    except Exception as e:
        print(f"[orchestrator] dispatch JSON backup failed: {e}")
    _db_sync_dispatch()


def _save_held() -> None:
    HOLD_PATH.write_text(json.dumps(sorted(_held_wos), indent=2))


def _save_validations() -> None:
    VALIDATIONS_PATH.write_text(json.dumps(_validations, indent=2))


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ── SQLite persistence ────────────────────────────────────────────────────────

def _init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
              wo TEXT PRIMARY KEY,
              slug TEXT DEFAULT '',
              agent TEXT DEFAULT '',
              backend TEXT DEFAULT '',
              workstation TEXT DEFAULT '',
              claimed_at TEXT,
              status TEXT DEFAULT 'claimed',
              step TEXT DEFAULT '',
              last_seen TEXT,
              completed_at TEXT,
              pr_url TEXT DEFAULT '',
              pr_number INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_steps (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              wo TEXT NOT NULL,
              ts TEXT NOT NULL,
              status TEXT NOT NULL,
              step TEXT DEFAULT '',
              agent TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_steps_wo ON run_steps(wo)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queue (
              wo          TEXT PRIMARY KEY,
              title       TEXT NOT NULL,
              phase       TEXT DEFAULT '',
              priority    TEXT NOT NULL DEFAULT 'P2',
              effort      TEXT DEFAULT '',
              position    INTEGER NOT NULL DEFAULT 9999,
              pin         INTEGER NOT NULL DEFAULT 0,
              blocks_milestones TEXT DEFAULT '[]',
              depends_on  TEXT DEFAULT '[]',
              notes       TEXT DEFAULT '',
              docs_required TEXT DEFAULT '[]',
              added_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phases (
              id          TEXT PRIMARY KEY,
              label       TEXT NOT NULL,
              target_date TEXT DEFAULT '',
              milestone_id TEXT,
              parallel    INTEGER NOT NULL DEFAULT 0,
              description TEXT DEFAULT '',
              position    INTEGER NOT NULL DEFAULT 9999
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS milestones (
              id          TEXT PRIMARY KEY,
              label       TEXT NOT NULL,
              target_date TEXT DEFAULT '',
              description TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS programs (
              id          TEXT PRIMARY KEY,
              label       TEXT NOT NULL,
              description TEXT DEFAULT '',
              added_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def _db_load_all_runs() -> dict[str, dict]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM runs").fetchall()
            return {row["wo"]: dict(row) for row in rows}
    except Exception:
        return {}


def _db_sync_dispatch() -> None:
    """Sync the in-memory _dispatch_state dict to SQLite — called from _save_dispatch()."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            existing = {row[0] for row in conn.execute("SELECT wo FROM runs").fetchall()}
            for wo_id in existing - set(_dispatch_state.keys()):
                conn.execute("DELETE FROM runs WHERE wo = ?", (wo_id,))
            for wo_id, record in _dispatch_state.items():
                conn.execute("""
                    INSERT INTO runs
                      (wo, slug, agent, backend, workstation, claimed_at, status,
                       step, last_seen, completed_at, pr_url, pr_number)
                    VALUES
                      (:wo, :slug, :agent, :backend, :workstation, :claimed_at, :status,
                       :step, :last_seen, :completed_at, :pr_url, :pr_number)
                    ON CONFLICT(wo) DO UPDATE SET
                      slug=excluded.slug, agent=excluded.agent, backend=excluded.backend,
                      workstation=excluded.workstation, claimed_at=excluded.claimed_at,
                      status=excluded.status, step=excluded.step,
                      last_seen=excluded.last_seen, completed_at=excluded.completed_at,
                      pr_url=excluded.pr_url, pr_number=excluded.pr_number
                """, {
                    "wo": wo_id,
                    "slug": record.get("slug", ""),
                    "agent": record.get("agent", ""),
                    "backend": record.get("backend", ""),
                    "workstation": record.get("workstation", ""),
                    "claimed_at": record.get("claimed_at"),
                    "status": record.get("status", "claimed"),
                    "step": record.get("step", ""),
                    "last_seen": record.get("last_seen"),
                    "completed_at": record.get("completed_at"),
                    "pr_url": record.get("pr_url", ""),
                    "pr_number": record.get("pr_number"),
                })
    except Exception as e:
        print(f"[db] sync_dispatch failed: {e}")


def _db_append_step(wo_id: str, status: str, step: str = "", agent: str = "") -> None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO run_steps (wo, ts, status, step, agent) VALUES (?, ?, ?, ?, ?)",
                (wo_id, _utcnow(), status, step, agent),
            )
    except Exception as e:
        print(f"[db] append_step failed for {wo_id}: {e}")


# ── Queue / phases / milestones DB helpers ────────────────────────────────────

def _db_get_queue() -> list[dict]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM queue ORDER BY position ASC, added_at ASC").fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["pin"] = bool(d.get("pin", 0))
                d["blocks_milestones"] = json.loads(d.get("blocks_milestones") or "[]")
                d["depends_on"] = json.loads(d.get("depends_on") or "[]")
                result.append(d)
            return result
    except Exception:
        return []


def _db_get_phases() -> list[dict]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM phases ORDER BY position ASC").fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["parallel"] = bool(d.get("parallel", 0))
                result.append(d)
            return result
    except Exception:
        return []


def _db_get_milestones() -> list[dict]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM milestones").fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _db_get_programs() -> list[dict]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT id, label, description, added_at FROM programs ORDER BY label").fetchall()
        return [{"id": r[0], "label": r[1], "description": r[2], "added_at": r[3]} for r in rows]
    except Exception:
        return []


def _db_upsert_program(id_: str, label: str, description: str = "") -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO programs (id, label, description) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET label=excluded.label, description=excluded.description",
            (id_, label, description),
        )
        conn.commit()


def _db_delete_program(id_: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM programs WHERE id = ?", (id_,))
        conn.commit()
    return cur.rowcount > 0


def _db_get_queue_wo_ids() -> set[str]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT wo FROM queue").fetchall()
            return {row[0] for row in rows}
    except Exception:
        return set()


def _db_build_plan_dict() -> dict:
    """Build a dict compatible with plan_engine.next_wo() / sorted_queue() from DB tables."""
    return {
        "phases": _db_get_phases(),
        "queue": _db_get_queue(),
    }


def _db_remove_done_wos(done_wo_ids: set[str]) -> int:
    if not done_wo_ids:
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            placeholders = ",".join("?" * len(done_wo_ids))
            cur = conn.execute(f"DELETE FROM queue WHERE wo IN ({placeholders})", list(done_wo_ids))
            conn.commit()
            return cur.rowcount
    except Exception as e:
        print(f"[db] remove_done_wos failed: {e}")
        return 0


def _db_upsert_queue_entry(entry: dict) -> None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM queue").fetchone()[0]
            conn.execute("""
                INSERT INTO queue
                  (wo, title, phase, priority, effort, position, pin,
                   blocks_milestones, depends_on, notes, docs_required)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wo) DO UPDATE SET
                  title=excluded.title, phase=excluded.phase, priority=excluded.priority,
                  effort=excluded.effort, pin=excluded.pin,
                  blocks_milestones=excluded.blocks_milestones,
                  depends_on=excluded.depends_on, notes=excluded.notes,
                  docs_required=excluded.docs_required
            """, (
                entry["wo"],
                entry.get("title", entry["wo"]),
                entry.get("phase", ""),
                entry.get("priority", "P2"),
                entry.get("effort", ""),
                entry.get("position", max_pos + 10),
                1 if entry.get("pin") else 0,
                json.dumps(entry.get("blocks_milestones", [])),
                json.dumps(entry.get("depends_on", [])),
                entry.get("notes", ""),
                entry.get("docs_required", "[]"),
            ))
            conn.commit()
    except Exception as e:
        print(f"[db] upsert_queue_entry failed for {entry.get('wo')}: {e}")


def _db_upsert_phase(phase: dict) -> None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM phases").fetchone()[0]
            conn.execute("""
                INSERT INTO phases (id, label, target_date, milestone_id, parallel, description, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  label=excluded.label, target_date=excluded.target_date,
                  milestone_id=excluded.milestone_id, parallel=excluded.parallel,
                  description=excluded.description
            """, (
                phase["id"],
                phase.get("label", phase["id"]),
                phase.get("target_date", ""),
                phase.get("milestone_id") or phase.get("milestone"),
                1 if phase.get("parallel") else 0,
                phase.get("description", ""),
                phase.get("position", max_pos + 10),
            ))
            conn.commit()
    except Exception as e:
        print(f"[db] upsert_phase failed for {phase.get('id')}: {e}")


def _db_upsert_milestone(milestone: dict) -> None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO milestones (id, label, target_date, description)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  label=excluded.label, target_date=excluded.target_date,
                  description=excluded.description
            """, (
                milestone["id"],
                milestone.get("label", milestone["id"]),
                milestone.get("target_date", ""),
                milestone.get("description", ""),
            ))
            conn.commit()
    except Exception as e:
        print(f"[db] upsert_milestone failed for {milestone.get('id')}: {e}")


def _migrate_plan_json_to_db() -> None:
    """One-time import of PLAN.json into the queue/phases/milestones tables. Idempotent."""
    sentinel = DATA_DIR / ".plan_migrated"
    if sentinel.exists():
        return

    plan_file: Path | None = None
    if LOCAL_REPO_MOUNT:
        candidate = Path(LOCAL_REPO_MOUNT) / PLAN_PATH
        if candidate.exists():
            plan_file = candidate

    if plan_file is None:
        sentinel.touch()
        return

    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[orchestrator] PLAN.json migration parse failed: {e}")
        sentinel.touch()
        return

    try:
        with sqlite3.connect(DB_PATH) as conn:
            existing_count = conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
            if existing_count > 0:
                sentinel.touch()
                return

            for i, w in enumerate(plan.get("queue", [])):
                conn.execute("""
                    INSERT OR IGNORE INTO queue
                      (wo, title, phase, priority, effort, position, pin,
                       blocks_milestones, depends_on, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    w["wo"],
                    w.get("title", w["wo"]),
                    w.get("phase", ""),
                    w.get("priority", "P2"),
                    w.get("effort", ""),
                    (i + 1) * 10,
                    1 if w.get("pin") else 0,
                    json.dumps(w.get("blocks_milestones", [])),
                    json.dumps(w.get("depends_on", [])),
                    w.get("notes", ""),
                ))

            for i, p in enumerate(plan.get("phases", [])):
                conn.execute("""
                    INSERT OR IGNORE INTO phases
                      (id, label, target_date, milestone_id, parallel, description, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["id"],
                    p.get("label", p["id"]),
                    p.get("target_date", ""),
                    p.get("milestone") or p.get("milestone_id"),
                    1 if p.get("parallel") else 0,
                    p.get("description", ""),
                    (i + 1) * 10,
                ))

            for m in plan.get("milestones", []):
                conn.execute("""
                    INSERT OR IGNORE INTO milestones (id, label, target_date, description)
                    VALUES (?, ?, ?, ?)
                """, (
                    m["id"],
                    m.get("label", m["id"]),
                    m.get("target_date", ""),
                    m.get("description", ""),
                ))

            conn.commit()
        print(f"[orchestrator] PLAN.json migrated to SQLite — {len(plan.get('queue', []))} queue entries, "
              f"{len(plan.get('phases', []))} phases, {len(plan.get('milestones', []))} milestones")
    except Exception as e:
        print(f"[orchestrator] PLAN.json migration to DB failed: {e}")

    sentinel.touch()


# ── Pydantic models ───────────────────────────────────────────────────────────

class ClaimRequest(BaseModel):
    wo: str           # e.g. "WO-359"
    agent: str        # agent runner name e.g. "claude-runner"
    backend: str = "" # actual AI backend: "claude" | "cursor" | "codex" | "gemini"
    workstation: str = ""
    slug: str = ""


class CompleteRequest(BaseModel):
    wo: str
    agent: str = ""
    pr_url: str = ""
    pr_number: int | None = None


class ValidateRequest(BaseModel):
    wo: str
    agent: str
    workstation: str = ""
    verify_url: str = ""
    steps: list[str] = []
    ci_passed: bool = True
    security_passed: bool = True
    thread_summary: str = ""
    pr_url: str = ""        # GitHub PR URL — must be non-empty before validation is accepted
    pr_number: int | None = None


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
    reason: str = ""  # alias used by claude-reviewer; prefer over notes

    def reject_reason(self) -> str:
        return self.reason or self.notes


class QueueEntryRequest(BaseModel):
    wo: str
    title: str
    phase: str = ""
    priority: str = "P2"
    effort: str = ""
    pin: bool = False
    blocks_milestones: list[str] = []
    depends_on: list[str] = []
    notes: str = ""
    docs_required: str = "[]"


class QueueUpdateRequest(BaseModel):
    title: str | None = None
    phase: str | None = None
    priority: str | None = None
    effort: str | None = None
    pin: bool | None = None
    blocks_milestones: list[str] | None = None
    depends_on: list[str] | None = None
    notes: str | None = None


class QueuePositionRequest(BaseModel):
    position: int | None = None
    before: str | None = None  # "WO-NNN" — insert before this WO


class PhaseRequest(BaseModel):
    id: str
    label: str
    target_date: str = ""
    milestone_id: str | None = None
    parallel: bool = False
    description: str = ""


class PhaseUpdateRequest(BaseModel):
    label: str | None = None
    target_date: str | None = None
    milestone_id: str | None = None
    parallel: bool | None = None
    description: str | None = None


class MilestoneRequest(BaseModel):
    id: str
    label: str
    target_date: str = ""
    description: str = ""


class MilestoneUpdateRequest(BaseModel):
    label: str | None = None
    target_date: str | None = None
    description: str | None = None


class ProgramCreate(BaseModel):
    id: str
    label: str
    description: str = ""


class ProgramUpdate(BaseModel):
    label: str | None = None
    description: str | None = None


# ── FastAPI app + lifespan ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    thread_store.THREADS_DIR.mkdir(parents=True, exist_ok=True)
    _load_state()
    _load_pm_memory()

    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[orchestrator] WARNING: GITHUB_TOKEN or GITHUB_REPO not set — poll loop disabled")
    else:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(poll, "interval", seconds=POLL_INTERVAL)
        scheduler.start()
        app.state.scheduler = scheduler
        # Fire first poll in background — store ref so it isn't GC'd
        app.state.initial_poll = asyncio.create_task(poll())

    start_slack_bot(secrets=_load_secrets())

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


@app.get("/api/metrics")
async def get_metrics():
    """Factory velocity metrics derived from dispatch history and validation records."""
    from collections import Counter
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    # Cycle times for completed WOs
    cycle_times: list[float] = []
    for info in _dispatch_state.values():
        if info.get("status") == "complete" and info.get("claimed_at") and info.get("completed_at"):
            try:
                c = datetime.fromisoformat(info["claimed_at"].replace("Z", "+00:00"))
                d = datetime.fromisoformat(info["completed_at"].replace("Z", "+00:00"))
                cycle_times.append((d - c).total_seconds() / 60)
            except Exception:
                pass

    status_counts = Counter(i.get("status") for i in _dispatch_state.values())
    val_counts = Counter(v.get("status") for v in _validations)
    rejections_by_wo: Counter = Counter()
    for v in _validations:
        if v.get("status") == "rejected":
            rejections_by_wo[v["wo"]] += 1

    total_val = len(_validations)
    approved = val_counts.get("approved", 0)
    rejected = val_counts.get("rejected", 0)
    plan = _orchestrator_output.get("plan", {})
    queue_depth = len(plan.get("queue", []))

    return {
        "queue_depth": queue_depth,
        "wos_complete": status_counts.get("complete", 0),
        "wos_active": sum(status_counts.get(s, 0) for s in ("claimed", "in_progress", "awaiting_human")),
        "wos_rejected": status_counts.get("rejected", 0),
        "held_count": len(_held_wos),
        "validations": {
            "total": total_val,
            "approved": approved,
            "rejected": rejected,
            "approval_rate_pct": round(approved / total_val * 100) if total_val else 0,
        },
        "cycle_time_minutes": {
            "avg": round(sum(cycle_times) / len(cycle_times)) if cycle_times else None,
            "min": round(min(cycle_times)) if cycle_times else None,
            "max": round(max(cycle_times)) if cycle_times else None,
            "samples": len(cycle_times),
        },
        "most_rejected_wos": [
            {"wo": wo, "rejections": n}
            for wo, n in rejections_by_wo.most_common(5)
        ],
        "held_wos": sorted(_held_wos),
        "generated_at": now.isoformat(),
    }


@app.get("/api/next")
async def get_next():
    """Return the highest-priority unclaimed WO, or null if none available."""
    global _pm_dispatch
    if _factory_paused:
        return {"wo": None, "reason": "factory paused — drain mode active"}

    active_statuses = {"claimed", "in_progress", "awaiting_human", "awaiting_commit", "complete"}

    # PM-dispatched WO takes priority over the normal queue
    if _pm_dispatch:
        dispatch = _pm_dispatch
        _pm_dispatch = None
        wo_id = dispatch["wo"]
        existing = _dispatch_state.get(wo_id, {})
        if existing.get("status") in active_statuses - {"complete"}:
            return {"wo": None, "reason": f"{wo_id} already active"}
        spec = _specs_cache.get(int(wo_id.replace("WO-", "")), {}) if _specs_cache else {}
        return {
            "wo": wo_id,
            "title": spec.get("title", dispatch.get("title", wo_id)),
            "priority": spec.get("priority", "P2"),
            "effort": spec.get("effort", "M"),
            "repo": spec.get("repo", GITHUB_REPO),
            "_dispatch_backend": dispatch.get("backend"),
        }

    plan = _orchestrator_output.get("plan", {})
    queue: list[dict] = plan.get("queue", [])

    active_count = sum(
        1 for c in _dispatch_state.values()
        if c.get("status") in active_statuses - {"complete"}
    )
    if active_count >= MAX_PARALLEL_WOS:
        return {"wo": None, "reason": f"at capacity ({active_count}/{MAX_PARALLEL_WOS} active)"}

    for wo in queue:
        wo_id = wo.get("wo", "")
        if wo_id in _held_wos:
            continue
        if _is_done(wo.get("status", "")):
            continue
        claim = _dispatch_state.get(wo_id, {})
        if claim.get("status") in active_statuses:
            continue
        # Dependency enforcement — skip WOs whose depends_on aren't complete yet
        deps = wo.get("depends_on") or []
        unmet = [d for d in deps if _dispatch_state.get(d, {}).get("status") != "complete"]
        if unmet:
            continue
        return {**wo, "repo": GITHUB_REPO}

    return {"wo": None, "reason": "queue empty or all candidates claimed/blocked"}


@app.post("/api/pm/dispatch")
async def pm_dispatch_wo(wo: str, backend: str = "claude"):
    """Store a PM-requested direct dispatch — picked up by the runner on next /api/next poll."""
    global _pm_dispatch
    wo_id = wo.upper() if wo.upper().startswith("WO-") else f"WO-{wo}"
    _pm_dispatch = {"wo": wo_id, "backend": backend}
    print(f"[orchestrator] PM dispatch queued: {wo_id} → {backend}")
    return {"ok": True, "wo": wo_id, "backend": backend}


@app.post("/api/pm/memory")
async def write_pm_memory(key: str, value: str):
    """Write a key/value pair into PM memory (preferences, decisions, dispatched)."""
    from datetime import UTC, datetime
    global _pm_memory
    today = datetime.now(UTC).date().isoformat()
    if key == "preferred_backend":
        _pm_memory.setdefault("preferences", {})["preferred_backend"] = value
        _pm_memory["preferences"]["last_updated"] = today
    elif key == "decision":
        _pm_memory.setdefault("recent_decisions", []).append({"date": today, "decision": value})
        _pm_memory["recent_decisions"] = _pm_memory["recent_decisions"][-20:]
    elif key == "dispatched":
        try:
            record = json.loads(value)
        except Exception:
            raise HTTPException(status_code=400, detail="dispatched value must be JSON: {wo, backend, outcome?}")
        record["date"] = today
        _pm_memory.setdefault("dispatched", []).append(record)
        _pm_memory["dispatched"] = _pm_memory["dispatched"][-50:]
    else:
        _pm_memory.setdefault("extra", {})[key] = value
    _save_pm_memory()
    return {"ok": True, "key": key}


@app.get("/api/pm/memory")
async def read_pm_memory():
    return _pm_memory


@app.get("/api/factory/pause")
async def get_pause_state():
    return {"paused": _factory_paused}


@app.post("/api/factory/pause")
async def pause_factory():
    """Stop claiming new WOs — in-flight agents finish their current WO then idle."""
    global _factory_paused
    _factory_paused = True
    PAUSE_PATH.write_text(json.dumps({"paused": True}))
    return {"paused": True, "message": "Factory draining — no new WOs will be claimed"}


@app.post("/api/factory/resume")
async def resume_factory():
    """Allow the runner to claim new WOs again."""
    global _factory_paused
    _factory_paused = False
    if PAUSE_PATH.exists():
        PAUSE_PATH.unlink()
    return {"paused": False, "message": "Factory resumed"}


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
    # Normalize WO ID: uppercase, ensure single "WO-" prefix
    wo_id = req.wo.strip()
    wo_upper = wo_id.upper()
    if not wo_upper.startswith("WO-"):
        wo_id = f"WO-{wo_id}"
    else:
        wo_id = wo_upper
    # Collapse accidental double-prefix (e.g. "WO-WO-353" → "WO-353")
    while wo_id.startswith("WO-WO-"):
        wo_id = "WO-" + wo_id[6:]
    existing = _dispatch_state.get(wo_id, {})
    active_statuses = {"claimed", "in_progress", "awaiting_human", "awaiting_commit"}

    if existing.get("status") in active_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"{wo_id} already claimed by {existing['agent']} on {existing.get('workstation', '?')}",
        )

    # Pre-dispatch approval gate: P1 WOs (and any in REQUIRE_APPROVAL_FOR) need human sign-off
    # unless already approved or skipped.
    wo_num = int(wo_id.replace("WO-", "")) if wo_id.replace("WO-", "").isdigit() else -1
    wo_spec = _specs_cache.get(wo_num, {})
    wo_priority = wo_spec.get("priority", "P2")
    skip_entry = _approval_skips.get(wo_id)
    skip_active = skip_entry and datetime.now(UTC) < datetime.fromisoformat(skip_entry)
    already_approved = existing.get("status") == "approved"
    needs_approval = (
        REQUIRE_APPROVAL_FOR
        and wo_priority in REQUIRE_APPROVAL_FOR
        and not already_approved
        and not skip_active
    )
    if needs_approval:
        is_new = existing.get("status") not in ("pending_approval",)
        _dispatch_state[wo_id] = {
            **existing,
            "wo": wo_id,
            "slug": req.slug or existing.get("slug", ""),
            "agent": req.agent,
            "workstation": req.workstation,
            "status": "pending_approval",
            "priority": wo_priority,
            "title": wo_spec.get("title", wo_id),
            "services": wo_spec.get("services", ""),
            "effort": wo_spec.get("effort", ""),
            "pending_since": existing.get("pending_since") or _utcnow(),
        }
        _save_dispatch()
        if is_new:
            thread_store.append_message(wo_id, thread_store.system_message(
                f"⏳ {wo_id} ({wo_priority}) awaiting pre-dispatch approval"
            ))
            asyncio.create_task(notify_factory_alert(
                title=f"{wo_id} needs approval before dispatch",
                body=f"{wo_spec.get('title', wo_id)} | Priority: {wo_priority} | Effort: {wo_spec.get('effort', '?')}",
                level="info",
                source="approval-gate",
                secrets=_load_secrets(),
            ))
        raise HTTPException(status_code=423, detail=f"{wo_id} is pending pre-dispatch approval")

    # Clear approval entry now that claim proceeds
    if already_approved:
        _dispatch_state.pop(wo_id, None)

    _dispatch_state[wo_id] = {
        "wo": wo_id,
        "slug": req.slug,
        "agent": req.agent,
        "backend": req.backend or req.agent,
        "workstation": req.workstation,
        "claimed_at": _utcnow(),
        "status": "claimed",
        "pr_url": "",
    }
    _save_dispatch()
    _db_append_step(wo_id, "claimed", agent=req.agent)
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


@app.get("/api/approvals")
async def list_approvals():
    """List WOs pending pre-dispatch approval."""
    pending = [
        entry for entry in _dispatch_state.values()
        if entry.get("status") == "pending_approval"
    ]
    return {"approvals": pending}


@app.post("/api/approvals/{wo_id}/approve")
async def approve_wo(wo_id: str):
    """Approve a WO for dispatch — agent will claim it on next poll."""
    wo_id = wo_id.upper()
    if not wo_id.startswith("WO-"):
        wo_id = f"WO-{wo_id}"
    entry = _dispatch_state.get(wo_id, {})
    if entry.get("status") != "pending_approval":
        raise HTTPException(status_code=404, detail=f"{wo_id} not in pending_approval state")
    _dispatch_state[wo_id]["status"] = "approved"
    _save_dispatch()
    thread_store.append_message(wo_id, thread_store.system_message(
        f"✅ {wo_id} approved for dispatch — agent will pick it up shortly"
    ))
    return {"ok": True, "wo": wo_id, "status": "approved"}


@app.post("/api/approvals/{wo_id}/skip")
async def skip_approval(wo_id: str):
    """Skip approval for 24h — WO re-enters queue and bypasses the gate temporarily."""
    wo_id = wo_id.upper()
    if not wo_id.startswith("WO-"):
        wo_id = f"WO-{wo_id}"
    _dispatch_state.pop(wo_id, None)
    skip_until = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    _approval_skips[wo_id] = skip_until
    _save_dispatch()
    thread_store.append_message(wo_id, thread_store.system_message(
        f"⏭ {wo_id} approval skipped — WO re-queued (approval bypassed for 24h)"
    ))
    return {"ok": True, "wo": wo_id, "skip_until": skip_until}


@app.post("/api/approvals/{wo_id}/hold")
async def hold_via_approval(wo_id: str):
    """Hold a WO from the approval queue — moves to held state."""
    wo_id = wo_id.upper()
    if not wo_id.startswith("WO-"):
        wo_id = f"WO-{wo_id}"
    _dispatch_state.pop(wo_id, None)
    _held_wos.add(wo_id)
    _save_dispatch()
    _save_held()
    thread_store.append_message(wo_id, thread_store.system_message(
        f"🚫 {wo_id} moved to held from approval queue"
    ))
    return {"ok": True, "wo": wo_id, "status": "held"}


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
    if not req.pr_url and not req.pr_number:
        gate_failures.append(
            "no GitHub PR attached — commit and push the branch, open a PR, then submit validation with pr_url"
        )
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
        "pr_url": req.pr_url,
        "pr_number": req.pr_number,
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
        secrets=_load_secrets(),
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
    # Reject ALL pending validations for this WO (duplicates accumulate when
    # multiple runners claim the same WO concurrently).
    rejected_count = 0
    for v in _validations:
        if v["wo"] == wo and v["status"] == "pending":
            v["status"] = "rejected"
            v["decided_by"] = decision.decided_by
            v["decided_at"] = _utcnow()
            v["notes"] = decision.notes
            v["reject_reason"] = decision.reject_reason()
            rejected_count += 1

    if rejected_count == 0:
        raise HTTPException(status_code=404, detail=f"No pending validation for {wo}")

    _save_validations()
    if wo in _dispatch_state:
        _dispatch_state[wo]["status"] = "rejected"
        _save_dispatch()

    thread_store.append_message(wo, thread_store.system_message(
        f"✗ Rejected by **{decision.decided_by}**"
        + (f"\n\nGuidance: {decision.notes}" if decision.notes else "")
    ))
    print(f"[orchestrator] {wo} rejected by {decision.decided_by} ({rejected_count} pending cleared): {decision.notes}")

    # Auto-hold the WO after 3 cumulative rejections so agents don't spin forever.
    total_rejections = sum(1 for v in _validations if v["wo"] == wo and v["status"] == "rejected")
    if total_rejections >= 3 and wo not in _held_wos:
        _held_wos.add(wo)
        thread_store.append_message(wo, thread_store.system_message(
            f"⛔ Auto-held after {total_rejections} rejections — human must review and un-hold before agents retry"
        ))
        print(f"[orchestrator] {wo} auto-held after {total_rejections} rejections")

    return {"ok": True, "rejected": rejected_count}


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


@app.post("/api/dispatch/{wo_id}/retry")
async def retry_dispatch(wo_id: str):
    """Reset a failed/stuck WO back to open so the runner picks it up again."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    if wo_id in _dispatch_state:
        del _dispatch_state[wo_id]
        _save_dispatch()
    print(f"[orchestrator] {wo_id} queued for retry (dispatch cleared)")
    return {"ok": True, "retrying": wo_id}


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
    if req.pr_url:
        _dispatch_state[wo_id]["pr_url"] = req.pr_url
    if req.pr_number:
        _dispatch_state[wo_id]["pr_number"] = req.pr_number
    _save_dispatch()
    _db_append_step(wo_id, "complete", step=f"merged by {req.agent}", agent=req.agent)
    # Remove from pending validations
    global _validations
    _validations = [v for v in _validations if v["wo"] != wo_id]
    _save_validations()
    thread_store.append_message(wo_id, thread_store.system_message(
        f"✅ WO complete — merged and closed by **{req.agent}**"
    ))
    print(f"[orchestrator] {wo_id} marked complete by {req.agent}")
    asyncio.create_task(notify_wo_complete(
        wo_id=wo_id, agent=req.agent, secrets=_load_secrets()
    ))
    return {"ok": True}


@app.post("/api/wos/{wo_id}/auto-mark-done")
async def auto_mark_done_wo(wo_id: str, pr_number: int | None = None,
                             merged_at: str | None = None, pr_url: str | None = None):
    """Push a mark-done commit to the target repo (via GitHub API) when a WO PR merges.

    Updates the WO spec file (Status → ✅ Done) and creates/updates the claim file,
    then commits both directly to main via GitHub's Contents API.
    Does not require git CLI — uses the GITHUB_TOKEN env var.
    """
    wo_id = wo_id.upper()
    if not wo_id.startswith("WO-"):
        wo_id = f"WO-{wo_id}"

    wo_num = wo_id.replace("WO-", "")
    now_iso = _utcnow()
    results: list[str] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=20) as client:
        # ── 1. Update spec file ──────────────────────────────────────────────
        try:
            files = await _cached_get(client, f"/repos/{GITHUB_REPO}/contents/{WO_PATH}",
                                       ttl=60)
            spec_file = next(
                (f for f in files if re.match(rf"WO-{wo_num}-", f["name"])),
                None,
            )
            if spec_file:
                file_data = await _get(client, f"/repos/{GITHUB_REPO}/contents/{spec_file['path']}")
                old_content = base64.b64decode(file_data["content"]).decode("utf-8")
                new_content = re.sub(
                    r"^\*\*Status:\*\*.*$",
                    "**Status:** ✅ Done",
                    old_content,
                    flags=re.MULTILINE,
                )
                if new_content != old_content:
                    payload: dict = {
                        "message": f"docs(pm): auto-mark {wo_id} done — PR #{pr_number} merged",
                        "content": base64.b64encode(new_content.encode()).decode(),
                        "sha": file_data["sha"],
                        "branch": "main",
                    }
                    resp = await client.put(
                        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{spec_file['path']}",
                        headers=_headers(), json=payload,
                    )
                    if resp.status_code in (200, 201):
                        results.append(f"spec {spec_file['name']} → ✅ Done")
                    else:
                        errors.append(f"spec push failed: {resp.status_code}")
                else:
                    results.append("spec already marked done")
        except Exception as e:
            errors.append(f"spec update error: {e}")

        # ── 2. Update / create claim file ────────────────────────────────────
        claim_path = f"{RUNS_PATH}/{wo_id}.json"
        try:
            claim_content = {
                "wo": int(wo_num) if wo_num.isdigit() else wo_num,
                "status": "done",
                "completed_at": merged_at or now_iso,
                "pr": pr_number,
                "pr_url": pr_url or "",
            }
            try:
                existing = await _get(client, f"/repos/{GITHUB_REPO}/contents/{claim_path}")
                old_claim = json.loads(base64.b64decode(existing["content"]).decode())
                old_claim.update(claim_content)
                claim_content = old_claim
                claim_sha: str | None = existing["sha"]
            except Exception:
                claim_sha = None

            claim_str = json.dumps(claim_content, indent=2) + "\n"
            payload = {
                "message": f"docs(pm): auto-mark {wo_id} done — claim file",
                "content": base64.b64encode(claim_str.encode()).decode(),
                "branch": "main",
            }
            if claim_sha:
                payload["sha"] = claim_sha
            resp = await client.put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{claim_path}",
                headers=_headers(), json=payload,
            )
            if resp.status_code in (200, 201):
                results.append(f"claim {wo_id}.json → done")
            else:
                errors.append(f"claim push failed: {resp.status_code}")
        except Exception as e:
            errors.append(f"claim update error: {e}")

    # ── 3. Mark orchestrator dispatch entry complete ─────────────────────────
    if wo_id in _dispatch_state:
        _dispatch_state[wo_id]["status"] = "complete"
        _dispatch_state[wo_id]["completed_at"] = now_iso
        if pr_url:
            _dispatch_state[wo_id]["pr_url"] = pr_url
        if pr_number:
            _dispatch_state[wo_id]["pr_number"] = pr_number
        _save_dispatch()
        _db_append_step(wo_id, "complete", step="auto-marked done by pr-watchdog")
        results.append("dispatch entry → complete")

    print(f"[orchestrator] auto-mark-done {wo_id}: {results}, errors: {errors}")
    return {"ok": not errors, "wo": wo_id, "results": results, "errors": errors}


@app.get("/api/notifications/config")
async def notifications_config():
    """Return ntfy topic and server URL (not sensitive — needed by the UI to display subscribe info)."""
    s = _load_secrets()
    topic = s.get("NTFY_TOPIC") or os.getenv("NTFY_TOPIC", "")
    server = s.get("NTFY_SERVER") or os.getenv("NTFY_SERVER", "https://ntfy.sh") or "https://ntfy.sh"
    return {"ntfy_topic": topic, "ntfy_server": server}


@app.post("/api/notifications/test")
async def notifications_test():
    """Send a test ntfy notification using current secrets config."""
    sent = await notify_test(secrets=_load_secrets())
    if not sent:
        raise HTTPException(status_code=422, detail="No notification channel configured — set NTFY_TOPIC or Slack Webhook in Settings → Authentication")
    return {"ok": True}


class _AlertRequest(BaseModel):
    title: str
    body: str
    level: str = "warning"
    source: str = "health-agent"


@app.post("/api/notifications/alert")
async def notifications_alert(req: _AlertRequest):
    """Post a factory health/infrastructure alert to ntfy and Slack."""
    await notify_factory_alert(
        title=req.title,
        body=req.body,
        level=req.level,
        source=req.source,
        secrets=_load_secrets(),
    )
    return {"ok": True}


@app.get("/api/slack/status")
async def slack_status():
    """Return whether the Slack bot is currently connected."""
    return {"connected": slack_is_connected()}


@app.post("/api/slack/reconnect")
async def slack_reconnect():
    """Reconnect the Slack bot using the current secrets store."""
    started = start_slack_bot(secrets=_load_secrets())
    return {"ok": True, "connected": started}


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


@app.get("/api/runs/{wo_id}/history")
async def get_run_history(wo_id: str):
    """Step audit log for a single WO — who did what and when."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM run_steps WHERE wo = ? ORDER BY ts",
                (wo_id,),
            ).fetchall()
            return {"wo": wo_id, "steps": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Queue CRUD endpoints ──────────────────────────────────────────────────────

@app.get("/api/queue")
async def list_queue():
    """Return all queue entries ordered by position."""
    return _db_get_queue()


@app.get("/api/queue/{wo_id}")
async def get_queue_entry(wo_id: str):
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM queue WHERE wo = ?", (wo_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"{wo_id} not in queue")
            d = dict(row)
            d["pin"] = bool(d.get("pin", 0))
            d["blocks_milestones"] = json.loads(d.get("blocks_milestones") or "[]")
            d["depends_on"] = json.loads(d.get("depends_on") or "[]")
            return d
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/queue")
async def add_to_queue(req: QueueEntryRequest):
    """Add a WO to the dispatch queue."""
    _db_upsert_queue_entry({
        "wo": req.wo,
        "title": req.title,
        "phase": req.phase,
        "priority": req.priority,
        "effort": req.effort,
        "pin": req.pin,
        "blocks_milestones": req.blocks_milestones,
        "depends_on": req.depends_on,
        "notes": req.notes,
        "docs_required": req.docs_required,
    })
    return {"ok": True, "wo": req.wo}


@app.put("/api/queue/{wo_id}")
async def update_queue_entry(wo_id: str, req: QueueUpdateRequest):
    """Update metadata for a queue entry (priority, effort, phase, notes, pin, blocks_milestones)."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT * FROM queue WHERE wo = ?", (wo_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"{wo_id} not in queue")
            updates: list[str] = []
            params: list = []
            if req.title is not None:
                updates.append("title=?"); params.append(req.title)
            if req.phase is not None:
                updates.append("phase=?"); params.append(req.phase)
            if req.priority is not None:
                updates.append("priority=?"); params.append(req.priority)
            if req.effort is not None:
                updates.append("effort=?"); params.append(req.effort)
            if req.pin is not None:
                updates.append("pin=?"); params.append(1 if req.pin else 0)
            if req.blocks_milestones is not None:
                updates.append("blocks_milestones=?"); params.append(json.dumps(req.blocks_milestones))
            if req.depends_on is not None:
                updates.append("depends_on=?"); params.append(json.dumps(req.depends_on))
            if req.notes is not None:
                updates.append("notes=?"); params.append(req.notes)
            if not updates:
                return {"ok": True, "wo": wo_id}
            params.append(wo_id)
            conn.execute(f"UPDATE queue SET {', '.join(updates)} WHERE wo = ?", params)
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "wo": wo_id}


@app.put("/api/queue/{wo_id}/position")
async def reorder_queue_entry(wo_id: str, req: QueuePositionRequest):
    """Reorder a queue entry. Pass position (absolute int) or before (WO ID to insert before)."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if req.before:
                before_id = req.before.upper() if req.before.upper().startswith("WO-") else f"WO-{req.before}"
                before_pos = conn.execute("SELECT position FROM queue WHERE wo = ?", (before_id,)).fetchone()
                if not before_pos:
                    raise HTTPException(status_code=404, detail=f"{before_id} not in queue")
                new_pos = before_pos[0] - 1
            elif req.position is not None:
                new_pos = req.position
            else:
                raise HTTPException(status_code=400, detail="Provide position or before")
            conn.execute("UPDATE queue SET position = ? WHERE wo = ?", (new_pos, wo_id))
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "wo": wo_id}


@app.delete("/api/queue/{wo_id}")
async def remove_from_queue(wo_id: str):
    """Remove a WO from the dispatch queue."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM queue WHERE wo = ?", (wo_id,))
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "wo": wo_id}


# ── Phases CRUD endpoints ─────────────────────────────────────────────────────

@app.get("/api/phases")
async def list_phases():
    return _db_get_phases()


@app.post("/api/phases")
async def create_phase(req: PhaseRequest):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute("SELECT id FROM phases WHERE id = ?", (req.id,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail=f"Phase '{req.id}' already exists")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    _db_upsert_phase(req.model_dump())
    return {"ok": True, "id": req.id}


@app.put("/api/phases/{phase_id}")
async def update_phase(phase_id: str, req: PhaseUpdateRequest):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT * FROM phases WHERE id = ?", (phase_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Phase '{phase_id}' not found")
            updates: list[str] = []
            params: list = []
            if req.label is not None:
                updates.append("label=?"); params.append(req.label)
            if req.target_date is not None:
                updates.append("target_date=?"); params.append(req.target_date)
            if req.milestone_id is not None:
                updates.append("milestone_id=?"); params.append(req.milestone_id)
            if req.parallel is not None:
                updates.append("parallel=?"); params.append(1 if req.parallel else 0)
            if req.description is not None:
                updates.append("description=?"); params.append(req.description)
            if updates:
                params.append(phase_id)
                conn.execute(f"UPDATE phases SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "id": phase_id}


@app.delete("/api/phases/{phase_id}")
async def delete_phase(phase_id: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM phases WHERE id = ?", (phase_id,))
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "id": phase_id}


# ── Milestones CRUD endpoints ─────────────────────────────────────────────────

@app.get("/api/milestones")
async def list_milestones():
    return _db_get_milestones()


@app.post("/api/milestones")
async def create_milestone(req: MilestoneRequest):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute("SELECT id FROM milestones WHERE id = ?", (req.id,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail=f"Milestone '{req.id}' already exists")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    _db_upsert_milestone(req.model_dump())
    return {"ok": True, "id": req.id}


@app.put("/api/milestones/{milestone_id}")
async def update_milestone(milestone_id: str, req: MilestoneUpdateRequest):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT * FROM milestones WHERE id = ?", (milestone_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Milestone '{milestone_id}' not found")
            updates: list[str] = []
            params: list = []
            if req.label is not None:
                updates.append("label=?"); params.append(req.label)
            if req.target_date is not None:
                updates.append("target_date=?"); params.append(req.target_date)
            if req.description is not None:
                updates.append("description=?"); params.append(req.description)
            if updates:
                params.append(milestone_id)
                conn.execute(f"UPDATE milestones SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "id": milestone_id}


@app.delete("/api/milestones/{milestone_id}")
async def delete_milestone(milestone_id: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM milestones WHERE id = ?", (milestone_id,))
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "id": milestone_id}


# ── Programs CRUD endpoints ───────────────────────────────────────────────────

@app.get("/api/programs")
async def list_programs():
    return JSONResponse(content=_db_get_programs())


@app.post("/api/programs", status_code=201)
async def create_program(req: ProgramCreate):
    existing = [p for p in _db_get_programs() if p["id"] == req.id]
    if existing:
        raise HTTPException(status_code=409, detail=f"Program '{req.id}' already exists")
    _db_upsert_program(req.id, req.label, req.description)
    return {"ok": True, "program_id": req.id}


@app.put("/api/programs/{program_id}")
async def update_program(program_id: str, req: ProgramUpdate):
    existing = next((p for p in _db_get_programs() if p["id"] == program_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found")
    label = req.label if req.label is not None else existing["label"]
    description = req.description if req.description is not None else existing["description"]
    _db_upsert_program(program_id, label, description)
    return {"ok": True}


@app.delete("/api/programs/{program_id}")
async def delete_program(program_id: str):
    if not _db_delete_program(program_id):
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found")
    return {"ok": True}


# ── Runner log stream (HTTP push from runner, SSE to browser) ─────────────────

class LogLine(BaseModel):
    line: str
    agent: str = ""


@app.post("/api/log")
async def append_log(entry: LogLine):
    """Runner posts each log line here; we buffer and broadcast to SSE clients."""
    global _log_buffer
    _log_buffer.append(entry.line)
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        _log_buffer = _log_buffer[-_LOG_BUFFER_MAX:]
    for q in list(_log_subscribers):
        try:
            q.put_nowait(entry.line)
        except asyncio.QueueFull:
            pass
    return {"ok": True}


@app.get("/api/log/stream")
async def stream_log(request: Request, agent: str = "", tail: int = 150):
    """SSE: send buffered history then stream new lines as runner posts them."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _log_subscribers.append(q)

    def _matches(line: str) -> bool:
        if not agent:
            return True
        low = line.lower()
        return agent.lower() in low

    async def generate():
        try:
            for line in _log_buffer[-tail:]:
                if _matches(line):
                    yield f"data: {json.dumps(line)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=2.0)
                    if _matches(line):
                        yield f"data: {json.dumps(line)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            try:
                _log_subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    # Match on status PREFIX only — substring matching causes "conflict advisor v1 done"
    # or "deferred to WO-226" to incorrectly mark a WO as done/deferred.
    # Strip markdown bold markers (**) that some legacy spec files use as a prefix.
    s = status.strip().lstrip("*").strip()
    sl = s.lower()
    return (
        s.startswith("✅") or s.startswith("⏸")
        or sl.startswith(("done", "complete", "completed", "deferred", "superseded", "abandoned"))
    )


def _is_ready(status: str) -> bool:
    """Return True if the WO is ready to dispatch (Open or explicitly marked Ready).

    📋 Planned WOs exist in the spec file but are not yet actionable — they
    must be promoted to 📋 Ready (or a plain 'open'/'ready' text status) before
    the orchestrator will put them in the dispatch queue.
    """
    s = status.strip().lstrip("*").strip()
    sl = s.lower()
    return (
        sl.startswith(("ready", "open"))
        or s.startswith("📋 Ready")
        or s.startswith("📋 Open")
    )


def _is_blocked(status: str) -> bool:
    s = status.strip()
    return s.startswith(("🔴", "❌")) or s.lower().startswith("blocked")


# ── GitHub data fetchers ──────────────────────────────────────────────────────

def _read_local_wo_specs(repo_root: str, wo_path: str, repo: str) -> dict[int, dict]:
    """Read WO spec files directly from the local filesystem mount."""
    specs: dict[int, dict] = {}
    wo_dir = Path(repo_root) / wo_path
    if not wo_dir.is_dir():
        return specs
    for f in wo_dir.glob("WO-*.md"):
        num = _parse_wo_number(f.name)
        if not num:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            specs[num] = {
                "number": num,
                "repo": repo,
                "title": _parse_title(content, num),
                "status": _parse_status(content),
                "priority": _parse_priority(content),
                "effort": _parse_effort(content),
                "depends_on": _parse_depends_on(content),
                "_raw_body": content,
            }
        except Exception as e:
            print(f"[orchestrator] Failed to read local WO-{num}: {e}")
    return specs


async def _fetch_wo_specs(client: httpx.AsyncClient, repo: str = GITHUB_REPO, wo_path: str = WO_PATH) -> dict[int, dict]:
    # Use local filesystem for primary repo — zero API calls
    if LOCAL_REPO_MOUNT and repo == GITHUB_REPO:
        specs = _read_local_wo_specs(LOCAL_REPO_MOUNT, wo_path, repo)
        if specs:
            return specs
        print(f"[orchestrator] Local WO specs empty, falling back to GitHub API")

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
                "_raw_body": content,
            }
        except Exception as e:
            print(f"[orchestrator] Failed to fetch WO-{num} from {repo}: {e}")
    return specs


async def _fetch_active_branches(client: httpx.AsyncClient, repo: str = GITHUB_REPO) -> set[int]:
    # Read from local git refs — no API call needed
    if LOCAL_REPO_MOUNT:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "branch", "-r", "--list", "origin/wo/*",
                cwd=LOCAL_REPO_MOUNT,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            results = set()
            for line in out.decode().splitlines():
                m = re.search(r"origin/wo/(\d+)-", line)
                if m:
                    results.add(int(m.group(1)))
            return results
        except Exception as e:
            print(f"[orchestrator] Local branch read failed: {e}")

    try:
        branches = await _get(client, f"/repos/{repo}/branches", {"per_page": 100})
        return {int(m.group(1)) for b in branches if (m := re.match(r"wo/(\d+)-", b["name"]))}
    except Exception:
        return set()


# Cache for PR data to reduce GitHub API calls (PRs can't be read locally)
_pr_cache: dict[str, tuple[float, object]] = {}
_PR_CACHE_TTL = 300  # 5 minutes


async def _cached_get(client: httpx.AsyncClient, url: str, params: dict, ttl: int = _PR_CACHE_TTL) -> list:
    import time
    key = f"{url}:{params}"
    cached_at, cached_val = _pr_cache.get(key, (0, []))
    if time.time() - cached_at < ttl:
        return cached_val  # type: ignore[return-value]
    try:
        val = await _get(client, url, params)
        _pr_cache[key] = (time.time(), val)
        return val
    except Exception:
        return cached_val  # type: ignore[return-value]


async def _fetch_open_pr_wos(client: httpx.AsyncClient, repo: str = GITHUB_REPO) -> set[int]:
    try:
        prs = await _cached_get(client, f"/repos/{repo}/pulls", {"state": "open", "per_page": 100})
        return {int(m.group(1)) for p in prs if (m := re.search(r"WO-(\d+)", p.get("title", "")))}
    except Exception:
        return set()


async def _fetch_dependabot_prs(client: httpx.AsyncClient) -> list[dict]:
    """Return open Dependabot PRs with CI status and mergeable state."""
    try:
        prs = await _cached_get(client, f"/repos/{GITHUB_REPO}/pulls",
                                 {"state": "open", "per_page": 100}, ttl=60)
        bot_prs = [p for p in prs if p.get("user", {}).get("login") == "dependabot[bot]"]
        results = []
        for pr in bot_prs:
            sha = pr.get("head", {}).get("sha", "")
            ci_state = "unknown"
            try:
                checks = await _get(client, f"/repos/{GITHUB_REPO}/commits/{sha}/check-runs",
                                     {"per_page": 100})
                runs = [r for r in checks.get("check_runs", [])
                        if "dependabot" not in r["name"].lower()]
                if runs:
                    if all(r.get("conclusion") in ("success", "skipped") for r in runs):
                        ci_state = "green"
                    elif any(r.get("conclusion") == "failure" for r in runs):
                        ci_state = "failed"
                    else:
                        ci_state = "pending"
                else:
                    ci_state = "pending"
            except Exception:
                pass
            # mergeable requires individual fetch — use cached PR data (may be stale)
            mergeable = pr.get("mergeable")  # None when not yet computed

            # Check if rebase is blocked ("edited by someone other than Dependabot")
            rebase_blocked = False
            try:
                comments = await _get(client, f"/repos/{GITHUB_REPO}/issues/{pr['number']}/comments",
                                       {"per_page": 20})
                for c in reversed(comments):
                    body = c.get("body", "")
                    if "edited by someone other than Dependabot" in body:
                        rebase_blocked = True
                        break
                    if c.get("user", {}).get("login") == "dependabot[bot]" and "rebase" in body.lower():
                        break  # latest dependabot comment is about something else
            except Exception:
                pass

            results.append({
                "number": pr["number"],
                "title": pr["title"],
                "branch": pr["head"]["ref"],
                "created_at": pr["created_at"][:10],
                "url": pr["html_url"],
                "mergeable": mergeable,
                "auto_merge": pr.get("auto_merge") is not None,
                "ci": ci_state,
                "rebase_blocked": rebase_blocked,
            })
        return results
    except Exception as exc:
        print(f"[dependabot] fetch error: {exc}")
        return []


async def _fetch_all_open_prs(client: httpx.AsyncClient) -> list[dict]:
    """Return all open PRs (non-Dependabot) with author, branch, CI state."""
    try:
        prs = await _cached_get(client, f"/repos/{GITHUB_REPO}/pulls",
                                 {"state": "open", "per_page": 100}, ttl=60)
        results = []
        for pr in prs:
            author = pr.get("user", {}).get("login", "unknown")
            sha = pr.get("head", {}).get("sha", "")
            ci_state = "unknown"
            try:
                checks = await _get(client, f"/repos/{GITHUB_REPO}/commits/{sha}/check-runs",
                                     {"per_page": 100})
                runs = checks.get("check_runs", [])
                if runs:
                    if all(r.get("conclusion") in ("success", "skipped") for r in runs):
                        ci_state = "green"
                    elif any(r.get("conclusion") == "failure" for r in runs):
                        ci_state = "failed"
                    else:
                        ci_state = "pending"
            except Exception:
                pass
            results.append({
                "number": pr["number"],
                "title": pr["title"],
                "author": author,
                "branch": pr["head"]["ref"],
                "created_at": pr["created_at"][:10],
                "url": pr["html_url"],
                "draft": pr.get("draft", False),
                "ci": ci_state,
            })
        return results
    except Exception as exc:
        print(f"[prs] fetch error: {exc}")
        return []


async def _fetch_merged_wo_count_this_week(client: httpx.AsyncClient) -> int:
    from datetime import timedelta
    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        prs = await _cached_get(client, f"/repos/{GITHUB_REPO}/pulls",
                                 {"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"},
                                 ttl=600)
        return sum(1 for p in prs if p.get("merged_at") and p["merged_at"] >= since)
    except Exception:
        return 0


async def _fetch_recently_merged_wo_prs(client: httpx.AsyncClient) -> dict[int, str]:
    """Return {wo_number: pr_html_url} for WO PRs merged in the last 90 days."""
    from datetime import timedelta
    since = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        prs = await _cached_get(client, f"/repos/{GITHUB_REPO}/pulls",
                                 {"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"},
                                 ttl=300)
        result: dict[int, str] = {}
        for p in prs:
            if p.get("merged_at") and p["merged_at"] >= since:
                m = re.search(r"WO-(\d+)", p.get("title", ""))
                if m:
                    result[int(m.group(1))] = p.get("html_url", "")
        return result
    except Exception:
        return {}


async def _fetch_plan(client: httpx.AsyncClient) -> dict | None:
    # Read PLAN.json from local filesystem — no API call
    if LOCAL_REPO_MOUNT:
        plan_file = Path(LOCAL_REPO_MOUNT) / PLAN_PATH
        if plan_file.exists():
            try:
                return json.loads(plan_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[orchestrator] Failed to read local PLAN.json: {e}")

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


def _validate_spec(wo_num: int, spec: dict) -> list[str]:
    """Return a list of validation errors for a WO spec; empty list means spec is complete."""
    errors: list[str] = []
    raw = spec.get("_raw_body", "")
    if len(raw) < SPEC_MIN_BODY_LENGTH:
        errors.append(f"spec too short ({len(raw)} chars < {SPEC_MIN_BODY_LENGTH} minimum) — likely a stub")
    raw_lower = raw.lower()
    for section in SPEC_REQUIRED_SECTIONS:
        if section.lower() not in raw_lower:
            errors.append(f"missing section: {section}")
    ac_lines = [ln for ln in raw.splitlines() if ln.strip().startswith("- [ ]")]
    if len(ac_lines) < SPEC_MIN_AC_ITEMS:
        errors.append(
            f"acceptance criteria has only {len(ac_lines)} checkbox item(s) — need at least {SPEC_MIN_AC_ITEMS}"
        )
    return errors


def _resolve_dependencies(
    specs: dict[int, dict],
    done_wos: set[int],
    dispatch_state: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    dispatch: list[dict] = []
    holding: list[dict] = []
    warnings: list[str] = []

    # WOs with an active dispatch entry are already claimed/running — skip them
    # so we don't issue a second dispatch for the same WO.
    claimed_wos: set[int] = set()
    if dispatch_state:
        for wo_id, entry in dispatch_state.items():
            if entry.get("status") in ("claimed", "complete", "rejected", "pending_approval"):
                try:
                    claimed_wos.add(int(wo_id.replace("WO-", "")))
                except ValueError:
                    pass

    def has_cycle(num: int, visiting: set[int]) -> bool:
        if num in visiting:
            return True
        deps = specs.get(num, {}).get("depends_on", [])
        return any(has_cycle(d, visiting | {num}) for d in deps if d in specs)

    for num, spec in sorted(specs.items(), key=lambda x: (x[1]["priority"], x[0])):
        if _is_done(spec["status"]):
            continue
        if num in claimed_wos:
            claimed_status = (dispatch_state or {}).get(f"WO-{num}", {}).get("status", "?")
            print(f"[dispatch] WO-{num} skipped — dispatch entry exists (status: {claimed_status})")
            continue
        if not _is_ready(spec["status"]):
            holding.append({
                "wo": num, "title": spec["title"], "priority": spec["priority"],
                "dependencies_met": False, "blocked_by": [],
                "reason": "Status is Planned — mark Ready to dispatch",
            })
            continue
        if has_cycle(num, set()):
            warnings.append(f"WO-{num} has a circular dependency — skipping")
            continue
        spec_errors = _validate_spec(num, spec)
        if spec_errors:
            reason = "; ".join(spec_errors)
            warnings.append(f"WO-{num} spec incomplete — holding: {reason}")
            holding.append({
                "wo": num, "title": spec["title"], "priority": spec["priority"],
                "dependencies_met": False, "blocked_by": [],
                "reason": f"Spec incomplete: {reason}",
            })
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

async def _sync_local_repo() -> None:
    """Pull latest from origin/main so local WO specs and PLAN.json stay fresh.

    Uses HTTPS with GITHUB_TOKEN to avoid SSH key requirements inside Docker.
    Runs once per poll cycle. Failures are logged but never block the poll.
    """
    if not LOCAL_REPO_MOUNT:
        return
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    https_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "fetch", https_url, "main:refs/remotes/origin/main",
            cwd=LOCAL_REPO_MOUNT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            print(f"[orchestrator] git fetch failed: {err.decode(errors='replace').strip()[:200]}")
            return
        proc2 = await asyncio.create_subprocess_exec(
            "git", "merge", "--ff-only", "refs/remotes/origin/main",
            cwd=LOCAL_REPO_MOUNT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out2, _ = await asyncio.wait_for(proc2.communicate(), timeout=10)
        if proc2.returncode == 0:
            msg = out2.decode(errors="replace").strip().splitlines()[0] if out2 else "ok"
            if "Already up to date" not in msg:
                print(f"[orchestrator] local repo synced: {msg}")
    except Exception as e:
        print(f"[orchestrator] git pull error: {e}")


async def poll() -> None:
    global _orchestrator_output
    now_str = _utcnow()
    _prev_output = _orchestrator_output  # keep last-good snapshot for rate-limit fallback

    await _sync_local_repo()  # keep local WO specs + PLAN.json fresh on every cycle

    async with httpx.AsyncClient(timeout=20) as client:
        # Primary repo fetches (always)
        primary_specs_task = _fetch_wo_specs(client, GITHUB_REPO, WO_PATH)
        active_branches_task = _fetch_active_branches(client, GITHUB_REPO)
        pr_wos_task = _fetch_open_pr_wos(client, GITHUB_REPO)
        merged_task = _fetch_merged_wo_count_this_week(client)
        merged_wo_prs_task = _fetch_recently_merged_wo_prs(client)

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
            merged_wo_prs_task,
            *secondary_tasks,
        )

    primary_specs: dict[int, dict] = results[0]
    active_branch_wos: set[int] = results[1]
    pr_wos: set[int] = results[2]
    merged_this_week: int = results[3]
    merged_wo_prs: dict[int, str] = results[4]  # {wo_num: pr_html_url}

    # If GitHub returned no specs (rate-limited or network error), preserve the last-good
    # output so the queue doesn't go empty and running WOs keep their position.
    if not primary_specs and _prev_output:
        print("[orchestrator] poll: GitHub returned empty specs — keeping last-good output (rate limit?)")
        _orchestrator_output = {**_prev_output, "generated_at": now_str, "stale": True}
        return

    # Stale claim sweep: release WOs whose agent stopped checking in.
    stale_released = []
    for wo_id, entry in list(_dispatch_state.items()):
        if entry.get("status") not in ("in_progress", "claimed"):
            continue
        last_seen = entry.get("last_seen")
        if not last_seen:
            continue
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(last_seen.replace("Z", "+00:00"))).total_seconds()
        except Exception:
            continue
        if age > CLAIM_TIMEOUT_SECONDS:
            agent_name = entry.get("agent", "unknown")
            age_min = int(age / 60)
            print(f"[orchestrator] {wo_id} stale claim ({age_min}m, agent={agent_name}) — releasing")
            _dispatch_state[wo_id]["status"] = "stale"
            _dispatch_state[wo_id]["stale_at"] = _utcnow()
            stale_released.append((wo_id, agent_name, age_min))
            thread_store.append_message(wo_id, thread_store.system_message(
                f"⚠️ Claim expired after {age_min} minutes — agent `{agent_name}` appears dead. Re-queuing."
            ))
    if stale_released:
        _save_dispatch()
        for wo_id, agent_name, age_min in stale_released:
            asyncio.create_task(notify_factory_alert(
                title=f"{wo_id} claim expired",
                body=f"Agent `{agent_name}` last checked in {age_min}m ago. WO re-queued.",
                level="warning",
                source="stale-claim-sweep",
                secrets=_load_secrets(),
            ))

    # Auto-reconcile: merged PRs → complete dispatch entries.
    # Creates stub entries for WOs that were merged without going through the
    # dispatch flow (e.g. cursor-runner completed and dispatch entry was lost).
    reconciled = 0
    for wo_num, pr_url in merged_wo_prs.items():
        wo_id = f"WO-{wo_num}"
        entry = _dispatch_state.get(wo_id)
        if entry is None:
            _dispatch_state[wo_id] = {
                "wo": wo_id,
                "slug": "",
                "agent": "unknown",
                "backend": "",
                "workstation": "",
                "claimed_at": _utcnow(),
                "status": "complete",
                "step": "PR merged",
                "last_seen": None,
                "completed_at": _utcnow(),
                "pr_url": pr_url,
                "pr_number": None,
            }
            _db_append_step(wo_id, "complete", step="PR merged (back-fill)")
            reconciled += 1
        elif entry.get("status") not in ("complete", "rejected"):
            entry["status"] = "complete"
            entry["completed_at"] = _utcnow()
            entry["step"] = "PR merged"
            entry["pr_url"] = pr_url
            _dispatch_state[wo_id] = entry
            _db_append_step(wo_id, "complete", step="PR merged (auto-reconcile)")
            reconciled += 1
    if reconciled:
        _save_dispatch()
        print(f"[orchestrator] poll: auto-completed {reconciled} WO(s) from merged PRs")

    # Merge secondary specs (secondary repos contribute board visibility only)
    # Never overwrite primary-repo specs — WO numbers can collide across repos
    specs: dict[int, dict] = dict(primary_specs)
    for sec_specs in results[5:]:
        for num, spec in sec_specs.items():
            if num not in specs:
                specs[num] = spec

    global _specs_cache
    _specs_cache = dict(specs)  # snapshot for PM chat context injection

    # Sets for board summary use all specs; dispatch queue uses primary-repo specs only
    done_wos = {num for num, s in specs.items() if _is_done(s["status"])}
    in_progress_wos = active_branch_wos - pr_wos - done_wos
    in_review_wos = pr_wos - done_wos
    open_wos = {num for num, s in specs.items()
                if not _is_done(s["status"]) and num not in active_branch_wos and num not in pr_wos}
    blocked_wos = {num for num, s in specs.items() if _is_blocked(s["status"])}

    # Plan engine only operates on primary repo WOs
    primary_open_wos = {num for num in open_wos if specs[num].get("repo", GITHUB_REPO) == GITHUB_REPO}

    # Build plan dict from DB (queue / phases / milestones)
    plan_dict = _db_build_plan_dict()
    wo_statuses = _build_wo_statuses(primary_specs, active_branch_wos, pr_wos,
                                     {n for n in done_wos if n in primary_specs})
    plan_next = next_wo(plan_dict, wo_statuses) if plan_dict.get("queue") else None
    plan_queue_sorted = sorted_queue(plan_dict, wo_statuses)

    dispatch_queue, holding_queue, cycle_warnings = _resolve_dependencies(
        {num: s for num, s in specs.items() if num in primary_open_wos}, done_wos,
        dispatch_state=_dispatch_state,
    )

    # Build runtime overlay — spec-file WOs not registered in the DB queue.
    # Uses prefix-based _is_done() so inline text like "deferred to WO-226" or
    # "conflict advisor v1 done" does NOT cause a WO to be excluded from the overlay.
    global _plan_overlay
    plan_registered = _db_get_queue_wo_ids()
    _plan_overlay = []
    for num, spec in sorted(specs.items()):
        wo_id = f"WO-{num}"
        if wo_id in plan_registered:
            continue
        if _is_done(spec.get("status", "")) or _is_blocked(spec.get("status", "")):
            continue
        if spec.get("repo", GITHUB_REPO) != GITHUB_REPO:
            continue  # secondary-repo WOs board-visible only, not dispatchable
        entry = {
            "wo": wo_id,
            "title": spec.get("title", wo_id),
            "priority": spec.get("priority", "P2"),
            "effort": spec.get("effort", ""),
            "status": spec.get("status", "open"),
            "_overlay": True,
        }
        _plan_overlay.append(entry)
        # Persist to SQLite so the queue stays current without manual PLAN.json edits.
        # ON CONFLICT DO UPDATE preserves any human-set position/pin/phase already in the DB.
        _db_upsert_queue_entry({**entry, "phase": spec.get("phase", "backlog")})

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

    # Auto-cleanup: remove done WOs from the DB queue so it stays current
    done_wo_ids = {f"WO-{n}" for n in done_wos if specs.get(n, {}).get("repo", GITHUB_REPO) == GITHUB_REPO}
    removed = _db_remove_done_wos(done_wo_ids)
    if removed:
        print(f"[orchestrator] poll: removed {removed} completed WO(s) from queue")

    _orchestrator_output = {
        "generated_at": now_str,
        "poll_interval_seconds": POLL_INTERVAL,
        "max_parallel_wos": MAX_PARALLEL_WOS,
        "pending_validations": len(pending_validations),
        "plan": {
            "loaded": True,
            "last_updated": None,
            "next": plan_next,
            "queue": plan_queue_sorted + _plan_overlay,
            "all_wos": _db_get_queue(),
            "deferred": [],
            "milestones": _db_get_milestones(),
            "phases": _db_get_phases(),
            "programs": _db_get_programs(),
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
            "overlay_wos": len(_plan_overlay),
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
    "force_cross_llm_review": True,
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
ANTHROPIC_USAGE_PATH = DATA_DIR / "anthropic_usage.json"

# Approximate cost per million tokens (USD) — update if Anthropic changes pricing
_ANTHROPIC_PRICING: dict[str, dict] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-opus-4-8":           {"input": 15.00, "output": 75.00},
}


def _record_anthropic_usage(model: str, input_tokens: int, output_tokens: int, endpoint: str) -> None:
    try:
        records = json.loads(ANTHROPIC_USAGE_PATH.read_text()) if ANTHROPIC_USAGE_PATH.exists() else []
        pricing = _ANTHROPIC_PRICING.get(model, {"input": 3.00, "output": 15.00})
        cost_usd = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        records.append({
            "ts": datetime.now(UTC).isoformat(),
            "model": model,
            "endpoint": endpoint,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
        })
        if len(records) > 2000:
            records = records[-2000:]
        ANTHROPIC_USAGE_PATH.write_text(json.dumps(records))
    except Exception:
        pass


@app.get("/api/anthropic-usage")
async def get_anthropic_usage():
    if not ANTHROPIC_USAGE_PATH.exists():
        return {"records": [], "summary": {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "call_count": 0}}
    try:
        records = json.loads(ANTHROPIC_USAGE_PATH.read_text())
    except Exception:
        records = []
    from datetime import timedelta
    day_ago = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    today = [r for r in records if r.get("ts", "") >= day_ago]
    return {
        "records": records[-10:],
        "summary": {
            "total_input_tokens": sum(r.get("input_tokens", 0) for r in records),
            "total_output_tokens": sum(r.get("output_tokens", 0) for r in records),
            "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in records), 4),
            "call_count": len(records),
            "today_input_tokens": sum(r.get("input_tokens", 0) for r in today),
            "today_output_tokens": sum(r.get("output_tokens", 0) for r in today),
            "today_cost_usd": round(sum(r.get("cost_usd", 0) for r in today), 4),
            "today_calls": len(today),
        },
    }


@app.get("/api/budget")
async def get_budget():
    """Aggregate token/spend budget across all configured AI providers."""
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    # ── Anthropic ──────────────────────────────────────────────────────────────
    anthropic: dict = {
        "available": True,
        "billing_type": "pay_as_you_go",
        "source": "local_tracking",
        "note": "Factory API calls only — does not include Claude Code CLI usage.",
    }
    try:
        records: list = json.loads(ANTHROPIC_USAGE_PATH.read_text()) if ANTHROPIC_USAGE_PATH.exists() else []
        month_recs = [r for r in records if r.get("ts", "") >= month_start]
        anthropic.update({
            "month_input_tokens":  sum(r.get("input_tokens",  0) for r in month_recs),
            "month_output_tokens": sum(r.get("output_tokens", 0) for r in month_recs),
            "month_cost_usd":      round(sum(r.get("cost_usd", 0) for r in month_recs), 4),
            "month_calls":         len(month_recs),
            "all_time_input_tokens":  sum(r.get("input_tokens",  0) for r in records),
            "all_time_output_tokens": sum(r.get("output_tokens", 0) for r in records),
            "all_time_cost_usd":      round(sum(r.get("cost_usd", 0) for r in records), 4),
        })
    except Exception as exc:
        anthropic["error"] = str(exc)

    # ── OpenAI ─────────────────────────────────────────────────────────────────
    openai_key = os.getenv("OPENAI_API_KEY") or _load_secrets().get("OPENAI_API_KEY", "")
    openai: dict = {"available": bool(openai_key)}
    if openai_key:
        try:
            import httpx as _httpx
            start_ts = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
            async with _httpx.AsyncClient(timeout=10) as _hc:
                _r = await _hc.get(
                    "https://api.openai.com/v1/organization/usage/completions",
                    params={"start_time": start_ts},
                    headers={"Authorization": f"Bearer {openai_key}"},
                )
            if _r.status_code == 200:
                _buckets = _r.json().get("data", [])
                openai.update({
                    "month_input_tokens":  sum(b.get("input_tokens",  0) for b in _buckets),
                    "month_output_tokens": sum(b.get("output_tokens", 0) for b in _buckets),
                    "billing_type": "pay_as_you_go",
                })
            else:
                openai["error"] = f"HTTP {_r.status_code}: {_r.text[:120]}"
        except Exception as exc:
            openai["error"] = str(exc)
    else:
        openai["note"] = "Set OPENAI_API_KEY in Settings → Authentication to enable"

    # ── Cursor ─────────────────────────────────────────────────────────────────
    cursor: dict = {
        "available": False,
        "billing_type": "monthly_quota",
        "known_limit_label": "500 fast requests / month (Pro)",
        "note": "No public API — check manually",
        "dashboard_url": "https://cursor.sh/settings",
    }

    # ── Gemini ─────────────────────────────────────────────────────────────────
    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
                  or _load_secrets().get("GEMINI_API_KEY", ""))
    gemini: dict = {"available": bool(gemini_key)}
    if not gemini_key:
        gemini["note"] = "Set GEMINI_API_KEY in Settings → Authentication to enable"
    else:
        gemini["note"] = "Usage via Google Cloud Monitoring — not yet implemented"

    return {
        "anthropic": anthropic,
        "openai":    openai,
        "cursor":    cursor,
        "gemini":    gemini,
        "generated_at": now.isoformat(),
        "month_start":  month_start,
    }


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

_DRAFT_SYSTEM_BASE = (
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


def _pm_situational_brief() -> str:
    """Build a ≤6000-char context brief for injection into PM draft/chat prompts."""
    lines: list[str] = []

    # Open WOs from spec cache
    if _specs_cache:
        open_wos = sorted(
            [(num, spec) for num, spec in _specs_cache.items()
             if not _is_done(spec.get("status", "")) and not _is_blocked(spec.get("status", ""))],
            key=lambda x: x[0],
        )
        if open_wos:
            lines.append("CURRENTLY OPEN WORK ORDERS:")
            for num, spec in open_wos[:15]:
                pri = spec.get("priority", "?")
                effort = spec.get("effort", "?")
                title = spec.get("title", f"WO-{num}")[:55]
                lines.append(f"  WO-{num} [{pri}/{effort}]: {title}")
        else:
            lines.append("CURRENTLY OPEN WORK ORDERS: none")

    # Queue order from DB
    queue = _db_get_queue()
    if queue:
        lines.append("")
        lines.append("PRIORITY QUEUE (next 10):")
        for i, entry in enumerate(queue[:10], 1):
            lines.append(f"  {i}. {entry['wo']}: {entry.get('title','')[:50]} [{entry.get('priority','?')}/{entry.get('effort','?')}]")

    # Phases and milestones
    phases = _db_get_phases()
    milestones = _db_get_milestones()
    if phases or milestones:
        lines.append("")
        lines.append("PHASES AND MILESTONES:")
        for p in phases:
            ms_tag = f" → milestone {p['milestone_id']}" if p.get("milestone_id") else ""
            date_tag = f" (target {p['target_date']})" if p.get("target_date") else ""
            lines.append(f"  Phase {p['id']}: {p['label']}{date_tag}{ms_tag}")
        for m in milestones:
            lines.append(f"  Milestone {m['id']}: {m['label']} — {m.get('target_date','TBD')}")

    # DOC_MAP summary
    if LOCAL_REPO_MOUNT:
        doc_map_path = Path(LOCAL_REPO_MOUNT) / "docs/factory/DOC_MAP.json"
        if doc_map_path.exists():
            try:
                doc_map = json.loads(doc_map_path.read_text(encoding="utf-8"))
                triggers = doc_map.get("triggers", [])
                if triggers:
                    lines.append("")
                    lines.append("DOCUMENTATION REQUIREMENTS (from DOC_MAP.json):")
                    lines.append("When the WO involves one of the following, add a 'Documentation Required' section:")
                    for t in triggers:
                        docs = ", ".join(d["file"].split("/")[-1] for d in t.get("docs_required", []))
                        lines.append(f"  [{t['id']}] {t['label']} → update: {docs}")
            except Exception:
                pass

    brief = "\n".join(lines)
    if len(brief) > 5500:
        brief = brief[:5500] + "\n[...truncated]"
    return brief


def _build_draft_system(brief: str) -> str:
    """Build the full PM draft system prompt with situational context injected."""
    if not brief:
        return _DRAFT_SYSTEM_BASE
    return (
        _DRAFT_SYSTEM_BASE
        + f"\n\n=== CURRENT FACTORY STATE ===\n{brief}\n\n"
        "Use this context to:\n"
        "- Set priority relative to existing open WOs (avoid creating a P1 if there are already 3 open P1s)\n"
        "- Set effort relative to similar WOs already in the queue\n"
        "- Set depends_on based on related open WOs listed above\n"
        "- Avoid duplicating work already in progress or recently shipped\n"
        "- Suggest an appropriate phase based on active phases above\n"
        "- If triggers from the Documentation Requirements section apply, add a "
        "'## Documentation Required' section listing the specific files to update"
    )


class DraftRequest(BaseModel):
    description: str
    next_wo_num: int = 1
    backend: str = "claude-api"
    program: str = ""
    priority: str = ""
    phase: str = ""
    effort: str = ""
    depends_on: str = ""


class PMChatRequest(BaseModel):
    message: str
    history: list[dict] = []   # [{role: "user"|"assistant", content: "..."}]
    backend: str = "claude-api"
    images: list[dict] = []    # [{data: "<base64>", media_type: "image/png"|...}]
    hints: dict = {}            # optional WO metadata: program, priority, phase, effort, depends_on


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
                result["exhausted_backends"] = data.get("exhausted_backends", [])
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
            hints = []
            if req.program:
                hints.append(f"Program: {req.program}")
            if req.priority:
                hints.append(f"Priority: {req.priority} (use this exact value)")
            if req.phase:
                hints.append(f"Phase: {req.phase}")
            if req.effort:
                hints.append(f"Effort: {req.effort} (use this exact value)")
            if req.depends_on:
                hints.append(f"Depends on: {req.depends_on}")
            hint_block = ("\n\nUser-provided hints (respect these in your output):\n" + "\n".join(hints)) if hints else ""
            draft_system = _build_draft_system(_pm_situational_brief())
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=draft_system,
                messages=[{
                    "role": "user",
                    "content": f"WO number: {req.next_wo_num:03d}\n\nRequest:\n{req.description}{hint_block}",
                }],
            )
            _record_anthropic_usage("claude-sonnet-4-6", msg.usage.input_tokens, msg.usage.output_tokens, "plan/draft")
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
                json={
                    "description": req.description,
                    "next_wo_num": req.next_wo_num,
                    "backend": backend,
                    "program": req.program,
                    "priority": req.priority,
                    "phase": req.phase,
                    "effort": req.effort,
                    "depends_on": req.depends_on,
                    "situational_brief": _pm_situational_brief(),
                },
            )
            if r.status_code == 200:
                return r.json()
            raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Agent runner not reachable. Start it with: make agent-once  (or make agent-install for the daemon)",
        )


# ── Dependabot PR endpoints ───────────────────────────────────────────────────

@app.get("/api/dependabot/prs")
async def list_dependabot_prs():
    """Return all open Dependabot PRs with CI status and mergeable state."""
    async with httpx.AsyncClient(timeout=15) as client:
        prs = await _fetch_dependabot_prs(client)
    return {"prs": prs}


@app.post("/api/dependabot/prs/{number}/rebase")
async def rebase_dependabot_pr(number: int):
    """Post @dependabot rebase comment to trigger a branch rebase."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues/{number}/comments",
            headers=_headers(),
            json={"body": "@dependabot rebase"},
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:200])
    return {"status": "rebase_triggered", "pr": number}


@app.post("/api/dependabot/prs/{number}/recreate")
async def recreate_dependabot_pr(number: int):
    """Post @dependabot recreate — used when rebase is blocked due to manual edits."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues/{number}/comments",
            headers=_headers(),
            json={"body": "@dependabot recreate"},
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:200])
    return {"status": "recreate_triggered", "pr": number}


@app.post("/api/dependabot/prs/{number}/approve-merge")
async def approve_merge_dependabot_pr(number: int):
    """Approve a Dependabot PR and merge it (squash). CI must be green."""
    async with httpx.AsyncClient(timeout=15) as client:
        approve_resp = await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{number}/reviews",
            headers=_headers(),
            json={"event": "APPROVE", "body": "✅ Approved by factory PM — CI green, patch/minor update."},
        )
        if approve_resp.status_code not in (200, 201):
            raise HTTPException(status_code=approve_resp.status_code,
                                detail=f"Approve failed: {approve_resp.text[:200]}")
        merge_resp = await client.put(
            f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{number}/merge",
            headers=_headers(),
            json={"merge_method": "squash"},
        )
        if merge_resp.status_code not in (200, 201):
            raise HTTPException(status_code=merge_resp.status_code,
                                detail=f"Merge failed: {merge_resp.text[:200]}")
    asyncio.create_task(notify_dependabot("merged", [number], secrets=_load_secrets()))
    return {"status": "merged", "pr": number}


# ── PM tool definitions ──────────────────────────────────────────────────────
_PM_TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the Clarion repository. Use to inspect source code, WO specs, "
            "docs, configs, or any project file before drafting a WO or answering a question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the repo root, e.g. 'src/clarion/api/routes/devices.py' or 'docs/project_management/work_orders/WO-376-canonical-entity-uuid.md'",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep_codebase",
        "description": (
            "Search for a text pattern across the repository. Returns matching lines with file paths. "
            "Use to find where something is defined, what APIs exist, or what code already handles a feature."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "grep regex pattern"},
                "path": {
                    "type": "string",
                    "description": "Optional subdirectory or file glob to narrow the search, e.g. 'src/clarion/' or '*.md'",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a repository directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path relative to repo root, e.g. 'src/clarion/api/routes/'",
                },
                "pattern": {
                    "type": "string",
                    "description": "Optional glob filter, e.g. '*.py' or 'WO-*.md'",
                },
            },
            "required": ["directory"],
        },
    },
    {
        "name": "git_log",
        "description": "Get recent git commit history, optionally filtered to a specific file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max commits to return (default 15)"},
                "path": {"type": "string", "description": "Optional file path to filter commits"},
            },
        },
    },
    {
        "name": "query_queue",
        "description": "Query the SQLite WO priority queue, phases, and milestones.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phase": {"type": "string", "description": "Filter by phase id, e.g. 'now' or 'backlog'"},
                "priority": {"type": "string", "description": "Filter by priority, e.g. 'P1'"},
            },
        },
    },
]


def _execute_pm_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a PM tool call. Returns a string result (always safe to include in messages)."""
    repo_root = Path(LOCAL_REPO_MOUNT).resolve() if LOCAL_REPO_MOUNT else None

    def _safe_path(rel: str) -> "Path | None":
        if not repo_root:
            return None
        try:
            target = (repo_root / rel).resolve()
            if not str(target).startswith(str(repo_root)):
                return None
            return target
        except Exception:
            return None

    if tool_name == "read_file":
        rel = tool_input.get("path", "").lstrip("/")
        if not repo_root:
            return "Error: repository not mounted (LOCAL_REPO_MOUNT not configured)"
        target = _safe_path(rel)
        if target is None:
            return "Error: path traversal not allowed"
        if not target.exists():
            return f"File not found: {rel}"
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) > 300:
                return "\n".join(lines[:300]) + f"\n\n[... truncated at 300 lines; file has {len(lines)} total]"
            return "\n".join(lines)
        except Exception as exc:
            return f"Error reading file: {exc}"

    if tool_name == "grep_codebase":
        if not repo_root:
            return "Error: repository not mounted"
        pattern = tool_input.get("pattern", "")
        search_path = tool_input.get("path", "")
        base = _safe_path(search_path) if search_path else repo_root
        if base is None:
            return "Error: invalid search path"
        try:
            import subprocess as _sp
            result = _sp.run(
                ["grep", "-r", "-n", "-m", "3",
                 "--include=*.py", "--include=*.ts", "--include=*.tsx",
                 "--include=*.md", "--include=*.json", "--include=*.sql",
                 pattern, str(base)],
                capture_output=True, text=True, timeout=10,
            )
            out = result.stdout.strip()
            if not out:
                return f"No matches for: {pattern}"
            lines = out.split("\n")[:60]
            return "\n".join(l.replace(str(repo_root) + "/", "") for l in lines)
        except Exception as exc:
            return f"Error: {exc}"

    if tool_name == "list_files":
        if not repo_root:
            return "Error: repository not mounted"
        directory = tool_input.get("directory", "").lstrip("/")
        pattern = tool_input.get("pattern", "*")
        target = _safe_path(directory)
        if target is None:
            return "Error: invalid directory"
        if not target.exists():
            return f"Directory not found: {directory}"
        try:
            files = sorted(target.glob(pattern))
            names = [str(f.relative_to(repo_root)) for f in files if f.is_file()][:100]
            if not names:
                return "No files found"
            return "\n".join(names)
        except Exception as exc:
            return f"Error: {exc}"

    if tool_name == "git_log":
        if not repo_root:
            return "Error: repository not mounted"
        limit = min(int(tool_input.get("limit") or 15), 30)
        path = tool_input.get("path", "")
        try:
            import subprocess as _sp
            cmd = ["git", "-C", str(repo_root), "log", f"--max-count={limit}",
                   "--oneline", "--no-decorate"]
            if path:
                cmd += ["--", path]
            result = _sp.run(cmd, capture_output=True, text=True, timeout=10)
            return result.stdout.strip() or "No commits found"
        except Exception as exc:
            return f"Error: {exc}"

    if tool_name == "query_queue":
        queue = _db_get_queue()
        phase_f = tool_input.get("phase")
        pri_f = tool_input.get("priority")
        if phase_f:
            queue = [e for e in queue if e.get("phase") == phase_f]
        if pri_f:
            queue = [e for e in queue if e.get("priority") == pri_f]
        return json.dumps({
            "queue": queue,
            "phases": _db_get_phases(),
            "milestones": _db_get_milestones(),
            "overlay_count": len(_plan_overlay),
        }, indent=2)

    return f"Unknown tool: {tool_name}"


_PM_SYSTEM = """\
You are the AI Factory PM for the Clarion project — a sharp, decisive engineering PM who knows the codebase.
You coordinate AI agents (Claude, Cursor, Codex, Gemini) that autonomously implement work orders (WOs).

{context}

PERSONALITY & STYLE:
- Be direct and decisive. Give recommendations, not questions back at the user.
- If you have enough context to answer, answer. Don't ask for information you already have.
- Keep replies short — 3-6 sentences max for status/advice. No bullet walls unless the user asks for detail.
- When asked "you tell me" or "what do you think" — commit to a clear recommendation.
- Never ask more than ONE follow-up question, and only if truly necessary to proceed.
- Use the WO spec content in context to give informed answers about dependencies, scope, and sequencing.

YOUR CAPABILITIES:
- Answer questions about active WOs, agent status, queue health, PR status
- Read WO specs, source code, docs, and any project file via the read_file tool
- Search the codebase for symbols, patterns, or existing implementations via grep_codebase
- List directory contents via list_files to understand project structure
- Check git history for recent changes via git_log
- Query the live priority queue, phases, and milestones via query_queue
- Draft new work orders from plain-English feature requests — always read relevant code first
- Trigger Dependabot actions (rebase, recreate, merge)
- Dispatch WOs directly to an agent backend
- Create and delete Programs, Phases, and Milestones
- Priorities: P1=core/risky, P2=feature/additive, P3=docs
- Effort: XS<1h S~2h M=½d L=1d XL=2-3d

TOOL USE GUIDANCE:
- Before drafting a WO spec, use read_file / grep_codebase to understand what code already exists.
- When the user asks about the codebase ("what does X do?", "where is Y?"), use the tools to look it up rather than guessing.
- When drafting WOs that touch a specific file or module, read that file first so the spec references real function names and patterns.
- Use query_queue to understand the current queue before advising on prioritization or sequencing.

PLANNING STRUCTURE — these three concepts organize work:
  Program  — what initiative a WO belongs to (e.g. "Launch Program"). Pure label; assign when creating a WO.
  Phase    — when a WO gets dispatched. "now" phase runs first, then "backlog". Controls dispatch order.
  Milestone — a delivery gate. WOs that block a milestone must all complete before it's declared done.

PLAN MANAGEMENT ACTIONS — emit at the END of your response after telling the user what you're creating/deleting:
  [CREATE_PROGRAM:id|label|description]
  [CREATE_PHASE:id|label|target_date]
  [CREATE_MILESTONE:id|label|target_date|description]
  [DELETE_PROGRAM:id]
  [DELETE_PHASE:id]
  [DELETE_MILESTONE:id]

  Rules for IDs: lowercase, hyphens only, no spaces (e.g. "launch-program", "q3-2026", "v1-beta")
  target_date format: YYYY-MM-DD or empty string
  description: plain text, no pipes allowed
  Example: User says "Create a program for security work"
    → Reply: "Creating a Security Hardening program for compliance-focused work."
    → Tag: [CREATE_PROGRAM:security-hardening|Security Hardening|Compliance and security posture improvements]

DISPATCH ACTION — emit at the END of your response when the user confirms they want to start a WO:
  [DISPATCH:WO-NNN:backend]  — claim WO-NNN and dispatch to backend (claude, cursor, codex, gemini)
  Example: [DISPATCH:WO-185:cursor]
  Only emit this when the user says "yes", "start it", "do it", "go ahead", or similar confirmation.
  Always tell the user which WO and backend you're dispatching before emitting the tag.

WO PR MERGE ACTION — use for WO PRs (non-Dependabot) when CI is green and user asks to merge:
  [PR:merge:NNN] — squash-merge PR #NNN directly (no approval step — avoids GitHub self-review 422)
  Example: [PR:merge:308]
  Use this for all WO PRs. NEVER use DEPENDABOT:approve-merge for WO PRs — it will 422.

DEPENDABOT PR ACTIONS — include action tags at the END of your response when needed:
  [DEPENDABOT:rebase:NNN]        — rebase PR #NNN (use when CONFLICTING and rebase_blocked=false)
  [DEPENDABOT:recreate:NNN]      — recreate PR #NNN from scratch (use when rebase_blocked=true)
  [DEPENDABOT:approve-merge:NNN] — approve + merge PR #NNN (use when CI green and MERGEABLE)
IMPORTANT: if rebase_blocked=true, NEVER use rebase — use recreate instead.

WHEN THE USER WANTS TO CREATE A WORK ORDER respond with ONLY this JSON (no other text, no fences):
{{"type":"wo_draft","title":"short action title ≤60 chars","priority":"P1|P2|P3","effort":"XS|S|M|L|XL","services":"comma-separated service names","problem":"2-3 sentences on the pain point","what_to_build":"technical description with files/approach","acceptance_criteria":["verifiable item 1","verifiable item 2","verifiable item 3"],"notes":"constraints or empty string"}}

FOR ALL OTHER MESSAGES respond in plain text only — no JSON, no markdown headers, no excessive bullet points.\
"""

_DEPENDABOT_KEYWORDS = frozenset([
    "dependabot", "dependency", "dependencies", "deps", "dep pr",
    "upgrade", "package update", "rebase", "conflicting pr",
])

_PR_KEYWORDS = frozenset([
    "pr", "prs", "pull request", "pull requests", "open pr", "current pr",
    "merge", "branch", "branches", "review",
])

_WO_STATUS_KEYWORDS = frozenset([
    "wo", "work order", "work orders", "queue", "queued", "next",
    "open", "pending", "ready", "planned", "in progress", "closed",
    "what's next", "whats next", "what is next", "status",
])


def _wo_status_summary() -> str:
    """Build a live WO status summary. Prefers the poll-cycle cache (includes secondary repos)."""
    if _specs_cache:
        specs = _specs_cache
    elif LOCAL_REPO_MOUNT:
        specs = _read_local_wo_specs(LOCAL_REPO_MOUNT, WO_PATH, GITHUB_REPO)
    else:
        return ""
    if not specs:
        return ""

    buckets: dict[str, list[str]] = {
        "in_progress": [], "ready": [], "open": [], "planned": [],
        "deferred": [], "done": [],
    }

    def _bucket(raw: str) -> str:
        s = raw.lower()
        if any(x in s for x in ("in progress", "in_progress", "active", "claimed")):
            return "in_progress"
        if "ready" in s:
            return "ready"
        if any(x in s for x in ("open", "partial")):
            return "open"
        if "planned" in s:
            return "planned"
        if any(x in s for x in ("defer", "deferred", "⏸")):
            return "deferred"
        return "done"

    for num in sorted(specs):
        w = specs[num]
        b = _bucket(w.get("status", ""))
        repo_tag = f" ({w['repo'].split('/')[-1]})" if w.get("repo") and w["repo"] != GITHUB_REPO else ""
        label = f"WO-{num}: {w.get('title', '')[:55]} [{w.get('priority','?')}]{repo_tag}"
        buckets[b].append(label)

    repos = sorted({v.get("repo", GITHUB_REPO) for v in specs.values()})
    lines = [f"WO status across {', '.join(repos)}:"]
    for key, label in [("in_progress", "In Progress"), ("ready", "Ready"),
                        ("open", "Open / Partial"), ("planned", "Planned")]:
        if buckets[key]:
            lines.append(f"{label} ({len(buckets[key])}):")
            lines.extend(f"  {e}" for e in buckets[key])
    lines.append(f"Done: {len(buckets['done'])} WOs")
    lines.append(f"Deferred: {len(buckets['deferred'])} WOs")
    return "\n".join(lines)


@app.post("/api/pm/chat")
async def pm_chat(req: PMChatRequest):
    """PM assistant — conversational AI with factory context. Returns text or a WO draft."""
    # Build factory context
    ctx_parts: list[str] = []
    if _dispatch_state:
        lines = [
            f"  {wo}: {info.get('status','?')} — {(info.get('step') or '')[:70]}"
            for wo, info in _dispatch_state.items()
        ]
        ctx_parts.append("Active WOs:\n" + "\n".join(lines))
    else:
        ctx_parts.append("Active WOs: none (runner is idle)")

    try:
        async with httpx.AsyncClient(timeout=3) as _c:
            _br = await _c.get(f"http://localhost:{API_PORT}/api/backends")
            if _br.status_code == 200:
                _b = _br.json()
                online = [k for k, v in _b.items() if v and k not in ("agent_runner_online",)]
                ctx_parts.append(f"Available AI backends: {', '.join(online) or 'none'}")
                ctx_parts.append(f"Agent runner: {'online' if _b.get('agent_runner_online') else 'offline'}")
    except Exception:
        pass

    # Inject live WO status when the message is about WO queue/status/next
    msg_lower = req.message.lower()

    # Inject full spec content for any WO numbers mentioned in the message or recent history
    mentioned_wos: set[int] = set()
    for text_src in [req.message] + [m["content"] for m in req.history[-6:] if isinstance(m.get("content"), str)]:
        for m in re.finditer(r"\bWO-(\d+)\b", text_src, re.IGNORECASE):
            mentioned_wos.add(int(m.group(1)))
    if mentioned_wos and LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / WO_PATH
        for num in sorted(mentioned_wos):
            matches = list(wo_dir.glob(f"WO-{num}-*.md"))
            # Skip AGENT-BRIEF files — use the main spec
            specs = [f for f in matches if "AGENT" not in f.name.upper() and "BRIEF" not in f.name.upper()]
            if specs:
                try:
                    content = specs[0].read_text(encoding="utf-8", errors="replace")
                    # Trim to first 120 lines to stay within context budget
                    trimmed = "\n".join(content.splitlines()[:120])
                    ctx_parts.append(f"WO-{num} spec:\n{trimmed}")
                except Exception:
                    pass

    if any(kw in msg_lower for kw in _WO_STATUS_KEYWORDS):
        summary = _wo_status_summary()
        if summary:
            ctx_parts.append("Current WO status (live from spec files):\n" + summary)
        elif _plan_overlay:
            lines = [f"  {w.get('wo','?')}: {w.get('title','')[:55]} [{w.get('priority','?')}] — {w.get('status','?')}"
                     for w in _plan_overlay[:20]]
            ctx_parts.append(f"Spec-file WOs available ({len(_plan_overlay)} total):\n" + "\n".join(lines))
        else:
            ctx_parts.append("No open WOs found in PLAN.json or spec files.")

    if any(kw in msg_lower for kw in _PR_KEYWORDS):
        try:
            async with httpx.AsyncClient(timeout=10) as _pc:
                all_prs = await _fetch_all_open_prs(_pc)
            if all_prs:
                lines = []
                for p in all_prs:
                    draft = " [DRAFT]" if p["draft"] else ""
                    lines.append(
                        f"  PR #{p['number']}{draft}: {p['title'][:60]} | by {p['author']} | CI={p['ci']} | branch={p['branch']}"
                    )
                ctx_parts.append(f"Open PRs in {GITHUB_REPO} ({len(all_prs)} total):\n" + "\n".join(lines))
            else:
                ctx_parts.append(f"Open PRs in {GITHUB_REPO}: none")
        except Exception:
            pass

    if any(kw in msg_lower for kw in _DEPENDABOT_KEYWORDS):
        try:
            async with httpx.AsyncClient(timeout=10) as _dc:
                dep_prs = await _fetch_dependabot_prs(_dc)
            if dep_prs:
                lines = []
                for p in dep_prs:
                    ci = p["ci"]
                    mg = p.get("mergeable") or "unknown"
                    am = "auto-merge enabled" if p["auto_merge"] else "no auto-merge"
                    lines.append(
                        f"  PR #{p['number']}: {p['title'][:60]} | CI={ci} | mergeable={mg} | {am}"
                        + (" | rebase_blocked=true (use recreate)" if p.get("rebase_blocked") else "")
                    )
                ctx_parts.append("Open Dependabot PRs:\n" + "\n".join(lines))
            else:
                ctx_parts.append("Open Dependabot PRs: none")
        except Exception:
            pass

    # Inject queue order + milestones into PM chat (condensed brief — no DOC_MAP)
    queue_snapshot = _db_get_queue()
    if queue_snapshot:
        lines = [f"  {i}. {e['wo']}: {e.get('title','')[:50]} [{e.get('priority','?')}]"
                 for i, e in enumerate(queue_snapshot[:10], 1)]
        ctx_parts.append("Priority queue (top 10):\n" + "\n".join(lines))
    milestones_snapshot = _db_get_milestones()
    if milestones_snapshot:
        lines = [f"  {m['id']}: {m['label']} — {m.get('target_date','TBD')}" for m in milestones_snapshot]
        ctx_parts.append("Milestones:\n" + "\n".join(lines))

    mem_summary = _pm_memory_summary()
    if mem_summary:
        ctx_parts.append("PM memory:\n" + mem_summary)

    system = _PM_SYSTEM.format(context="\n".join(ctx_parts))
    messages = [{"role": m["role"], "content": m["content"]} for m in req.history]

    # Append WO metadata hints to message if provided
    user_message = req.message
    if req.hints:
        hint_lines = [f"  {k}: {v}" for k, v in req.hints.items() if v]
        if hint_lines:
            user_message = user_message + "\n\n[User-specified WO metadata — use these exact values in the draft:\n" + "\n".join(hint_lines) + "]"

    text = ""
    if req.backend == "claude-api" or not req.backend:
        api_key = _get_anthropic_key()
        if api_key:
            try:
                import anthropic as _anthropic
                _aclient = _anthropic.Anthropic(api_key=api_key)
                _model = "claude-sonnet-4-6"
                tools = _PM_TOOLS if LOCAL_REPO_MOUNT else []
                tool_messages = list(messages)
                tool_messages.append({"role": "user", "content": user_message if not req.images else [
                    *[{"type": "image", "source": {"type": "base64", "media_type": img.get("media_type", "image/png"), "data": img["data"]}} for img in req.images],
                    *([] if not user_message else [{"type": "text", "text": user_message}]),
                ]})
                _amsg = _aclient.messages.create(
                    model=_model,
                    max_tokens=4096,
                    system=system,
                    messages=tool_messages,
                    tools=tools or _anthropic.NOT_GIVEN,
                )
                _record_anthropic_usage(_model, _amsg.usage.input_tokens, _amsg.usage.output_tokens, "pm/chat")
                # Tool-use loop — PM may call tools before producing final text
                _MAX_TOOL_ROUNDS = 6
                for _round in range(_MAX_TOOL_ROUNDS):
                    if _amsg.stop_reason != "tool_use":
                        break
                    tool_calls = [b for b in _amsg.content if b.type == "tool_use"]
                    tool_messages.append({"role": "assistant", "content": [b.model_dump() for b in _amsg.content]})
                    tool_results = []
                    for tc in tool_calls:
                        result = _execute_pm_tool(tc.name, tc.input)
                        tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": result})
                    tool_messages.append({"role": "user", "content": tool_results})
                    _amsg = _aclient.messages.create(
                        model=_model,
                        max_tokens=4096,
                        system=system,
                        messages=tool_messages,
                        tools=tools or _anthropic.NOT_GIVEN,
                    )
                    _record_anthropic_usage(_model, _amsg.usage.input_tokens, _amsg.usage.output_tokens, "pm/chat")
                text = "".join(b.text for b in _amsg.content if hasattr(b, "text")).strip()
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        elif req.images:
            # Images require the API — CLI backends cannot accept binary image data
            raise HTTPException(
                status_code=422,
                detail="Image input requires an Anthropic API key. Add one in Settings → Agents, or send a text-only message.",
            )
        else:
            # Text-only: fall through to CLI backend
            req = PMChatRequest(message=req.message, history=req.history, backend="cursor")

    if not text:
        # CLI backend via draft server
        try:
            async with httpx.AsyncClient(timeout=60) as _c:
                _r = await _c.post(
                    f"{AGENT_RUNNER_URL}/api/chat",
                    json={"system": system, "message": user_message, "history": req.history,
                          "backend": req.backend if req.backend != "claude-api" else None},
                )
                if _r.status_code != 200:
                    raise HTTPException(status_code=_r.status_code, detail=_r.text[:300])
                text = _r.json().get("reply", "")
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail="No AI backend available. Set an Anthropic API key in Settings → Authentication.",
            )

    # Detect WO draft JSON response
    stripped = text.strip()
    if stripped.startswith("{") and '"type"' in stripped and '"wo_draft"' in stripped:
        try:
            data = json.loads(stripped)
            if data.get("type") == "wo_draft":
                return {"type": "wo_draft", "reply": "", "wo_draft": data}
        except json.JSONDecodeError:
            pass

    # Parse and execute Dependabot action tags, e.g. [DEPENDABOT:rebase:278]
    action_pattern = re.compile(r"\[DEPENDABOT:(rebase|recreate|approve-merge):(\d+)\]")
    action_results: list[str] = []
    clean_text = text
    for match in action_pattern.finditer(text):
        action, pr_num = match.group(1), int(match.group(2))
        clean_text = clean_text.replace(match.group(0), "").strip()
        try:
            async with httpx.AsyncClient(timeout=15) as _ac:
                if action == "rebase":
                    resp = await _ac.post(
                        f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_num}/comments",
                        headers=_headers(), json={"body": "@dependabot rebase"},
                    )
                    action_results.append(
                        f"✅ Triggered rebase on PR #{pr_num}" if resp.status_code in (200, 201)
                        else f"⚠️ Rebase on PR #{pr_num} failed ({resp.status_code})"
                    )
                elif action == "recreate":
                    resp = await _ac.post(
                        f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_num}/comments",
                        headers=_headers(), json={"body": "@dependabot recreate"},
                    )
                    action_results.append(
                        f"✅ Triggered recreate on PR #{pr_num} — Dependabot will open a fresh PR against main" if resp.status_code in (200, 201)
                        else f"⚠️ Recreate on PR #{pr_num} failed ({resp.status_code})"
                    )
                elif action == "approve-merge":
                    ar = await _ac.post(
                        f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}/reviews",
                        headers=_headers(),
                        json={"event": "APPROVE", "body": "✅ Approved by factory PM."},
                    )
                    if ar.status_code in (200, 201):
                        mr = await _ac.put(
                            f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}/merge",
                            headers=_headers(), json={"merge_method": "squash"},
                        )
                        action_results.append(
                            f"✅ Approved and merged PR #{pr_num}" if mr.status_code in (200, 201)
                            else f"⚠️ PR #{pr_num} approved but merge failed ({mr.status_code}: {mr.text[:100]})"
                        )
                    else:
                        action_results.append(f"⚠️ Approve on PR #{pr_num} failed ({ar.status_code})")
        except Exception as exc:
            action_results.append(f"⚠️ Action {action} on PR #{pr_num} errored: {exc}")

    if action_results:
        clean_text = clean_text + "\n\n" + "\n".join(action_results)

    # Parse and execute WO PR merge tags, e.g. [PR:merge:308]
    # Does NOT attempt a GitHub review (which would 422 as self-review); squash-merges directly.
    pr_merge_pattern = re.compile(r"\[PR:merge:(\d+)\]")
    pr_merge_results: list[str] = []
    for match in pr_merge_pattern.finditer(clean_text):
        pr_num = int(match.group(1))
        clean_text = clean_text.replace(match.group(0), "").strip()
        try:
            async with httpx.AsyncClient(timeout=15) as _ac:
                mr = await _ac.put(
                    f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}/merge",
                    headers=_headers(), json={"merge_method": "squash"},
                )
                if mr.status_code in (200, 201):
                    pr_merge_results.append(f"✅ Merged PR #{pr_num} (squash)")
                    # Auto-complete the owning WO dispatch entry
                    try:
                        async with httpx.AsyncClient(timeout=10) as _pc:
                            pr_resp = await _pc.get(
                                f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}",
                                headers=_headers(),
                            )
                            if pr_resp.status_code == 200:
                                pr_data = pr_resp.json()
                                pr_html = pr_data.get("html_url", "")
                                m_wo = re.search(r"WO-(\d+)", pr_data.get("title", ""))
                                if m_wo:
                                    wo_match = f"WO-{m_wo.group(1)}"
                                    if wo_match in _dispatch_state and _dispatch_state[wo_match].get("status") not in ("complete", "rejected"):
                                        _dispatch_state[wo_match]["status"] = "complete"
                                        _dispatch_state[wo_match]["completed_at"] = _utcnow()
                                        _dispatch_state[wo_match]["step"] = f"PR #{pr_num} merged via PM"
                                        _dispatch_state[wo_match]["pr_url"] = pr_html
                                        _dispatch_state[wo_match]["pr_number"] = pr_num
                                        _save_dispatch()
                                        _db_append_step(wo_match, "complete", step=f"PR #{pr_num} merged via PM")
                                        print(f"[orchestrator] auto-completed {wo_match} after PM merged PR #{pr_num}")
                    except Exception as ex:
                        print(f"[orchestrator] auto-complete after merge PR #{pr_num} failed: {ex}")
                elif mr.status_code == 405:
                    pr_merge_results.append(f"⚠️ PR #{pr_num} not mergeable yet — CI may still be running")
                else:
                    pr_merge_results.append(f"⚠️ Merge PR #{pr_num} failed ({mr.status_code}: {mr.text[:120]})")
        except Exception as exc:
            pr_merge_results.append(f"⚠️ Merge PR #{pr_num} errored: {exc}")

    if pr_merge_results:
        clean_text = clean_text + "\n\n" + "\n".join(pr_merge_results)

    # Parse and execute DISPATCH action tags, e.g. [DISPATCH:WO-375:cursor]
    dispatch_pattern = re.compile(r"\[DISPATCH:(WO-\d+|\d+):([\w-]+)\]")
    dispatch_results: list[str] = []
    for match in dispatch_pattern.finditer(clean_text):
        raw_wo, backend = match.group(1), match.group(2)
        wo_id = raw_wo if raw_wo.startswith("WO-") else f"WO-{raw_wo}"
        clean_text = clean_text.replace(match.group(0), "").strip()
        try:
            async with httpx.AsyncClient(timeout=10) as _dc:
                # Queue in orchestrator so /api/next returns it
                await _dc.post(
                    f"http://localhost:{API_PORT}/api/pm/dispatch",
                    params={"wo": wo_id, "backend": backend},
                )
                # Try to wake the runner immediately so it doesn't wait for the next poll
                runner_woke = False
                try:
                    await _dc.post(
                        f"{AGENT_RUNNER_URL}/dispatch",
                        json={"wo": wo_id, "backend": backend},
                        timeout=3,
                    )
                    runner_woke = True
                except Exception:
                    pass
                dispatch_results.append(
                    f"✅ {wo_id} dispatched to {backend} — {'runner woke up' if runner_woke else 'runner picks it up on next poll'}"
                )
                # Persist to PM memory
                from datetime import UTC, datetime
                _pm_memory.setdefault("dispatched", []).append({
                    "wo": wo_id, "backend": backend,
                    "date": datetime.now(UTC).date().isoformat(),
                })
                _pm_memory["dispatched"] = _pm_memory["dispatched"][-50:]
                _save_pm_memory()
        except Exception as exc:
            dispatch_results.append(f"⚠️ Dispatch of {wo_id} failed: {exc}")

    if dispatch_results:
        clean_text = clean_text + "\n\n" + "\n".join(dispatch_results)

    # Parse and execute plan management actions: CREATE/DELETE for programs, phases, milestones
    plan_action_pattern = re.compile(
        r"\[(CREATE_PROGRAM|CREATE_PHASE|CREATE_MILESTONE|DELETE_PROGRAM|DELETE_PHASE|DELETE_MILESTONE):([^\]]+)\]"
    )
    plan_action_results: list[str] = []
    for match in plan_action_pattern.finditer(clean_text):
        action = match.group(1)
        args = match.group(2).split("|")
        clean_text = clean_text.replace(match.group(0), "").strip()
        try:
            if action == "CREATE_PROGRAM":
                id_ = args[0].strip()
                label = args[1].strip() if len(args) > 1 else id_
                desc = args[2].strip() if len(args) > 2 else ""
                _db_upsert_program(id_, label, desc)
                plan_action_results.append(f"✅ Program created: **{label}**")
            elif action == "CREATE_PHASE":
                id_ = args[0].strip()
                label = args[1].strip() if len(args) > 1 else id_
                target_date = args[2].strip() if len(args) > 2 else ""
                _db_upsert_phase({"id": id_, "label": label, "target_date": target_date})
                plan_action_results.append(f"✅ Phase created: **{label}**")
            elif action == "CREATE_MILESTONE":
                id_ = args[0].strip()
                label = args[1].strip() if len(args) > 1 else id_
                target_date = args[2].strip() if len(args) > 2 else ""
                desc = args[3].strip() if len(args) > 3 else ""
                _db_upsert_milestone({"id": id_, "label": label, "target_date": target_date, "description": desc})
                plan_action_results.append(f"✅ Milestone created: **{label}**")
            elif action == "DELETE_PROGRAM":
                id_ = args[0].strip()
                ok = _db_delete_program(id_)
                plan_action_results.append(f"✅ Program deleted: {id_}" if ok else f"⚠️ Program '{id_}' not found")
            elif action == "DELETE_PHASE":
                id_ = args[0].strip()
                with _db_connect() as conn:
                    cur = conn.execute("DELETE FROM phases WHERE id = ?", (id_,))
                    conn.commit()
                plan_action_results.append(f"✅ Phase deleted: {id_}" if cur.rowcount > 0 else f"⚠️ Phase '{id_}' not found")
            elif action == "DELETE_MILESTONE":
                id_ = args[0].strip()
                with _db_connect() as conn:
                    cur = conn.execute("DELETE FROM milestones WHERE id = ?", (id_,))
                    conn.commit()
                plan_action_results.append(f"✅ Milestone deleted: {id_}" if cur.rowcount > 0 else f"⚠️ Milestone '{id_}' not found")
        except Exception as exc:
            plan_action_results.append(f"⚠️ {action} failed: {exc}")

    if plan_action_results:
        clean_text = clean_text + "\n\n" + "\n".join(plan_action_results)

    return {"type": "text", "reply": clean_text.strip(), "wo_draft": None}


if __name__ == "__main__":
    uvicorn.run("orchestrator:app", host="0.0.0.0", port=API_PORT, log_level="info")
