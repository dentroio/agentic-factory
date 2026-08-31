import asyncio
import base64
import hashlib
import json
import os
import secrets as _secrets_mod
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
import intelligence as _intel
from wo_resolver import (
    resolve_wo_for_pr,
    resolve_wo_for_pr_with_source,
    resolve_all_wos_for_pr,
    extract_wo_from_branch,
    extract_wo_from_title,
    classify_wo_status,
    wos_completed_by_merged_pr,
)
import dispatch_control
import occupancy
import conflict_advisor
from db import (
    connect as _db_connect,
    remember_runs as _db_remember_runs,
    schedule_sync_runs as _db_schedule_sync_runs,
    sync_runs as _db_sync_runs,
    init_history_table as _db_init_history_table,
    record_run_history as _db_record_run_history,
    get_run_history as _db_get_run_history,
    get_run_metrics as _db_get_run_metrics,
)
from agent_config_policy import AgentConfigError, apply_agent_config_updates
from git_https import git_fetch_env, github_https_url, redact_secret
from llm_client import messages_create
from runner_agents import RunnerAgentError, parse_configure_body, require_runner_agent
from secrets_policy import SecretPolicyError, apply_secret_updates
from vault_auth import load_vault_token

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
INTELLIGENCE_INTERVAL = int(os.getenv("INTELLIGENCE_INTERVAL", "600"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
# 900s (15min) with a margin above the 90s runner heartbeat interval — the
# heartbeat fix (runner.py _checkin_loop wrapping rebuild/quality-gate) is
# the real fix for the false-positive-stale race, this is defense in depth
# in case a heartbeat itself is dropped (network blip, orchestrator restart
# mid-step). Was 600s (10min); WO-440's quality gate alone hit a 900s make
# timeout on its own, so 600s was already too tight even before counting the
# rebuild step ahead of it.
CLAIM_TIMEOUT_SECONDS = int(os.getenv("CLAIM_TIMEOUT_SECONDS", "1200"))
MAX_PARALLEL_WOS = int(os.getenv("MAX_PARALLEL_WOS", "2"))
MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
REQUIRE_APPROVAL_FOR: set[str] = {p.strip() for p in os.getenv("REQUIRE_APPROVAL_FOR", "P1").split(",") if p.strip()}
CLARION_API_URL = os.getenv("CLARION_API_URL", "http://localhost:8000")
PREFLIGHT_RETRY_SECONDS = 1800  # re-check held WOs every 30 minutes
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
SPEC_MIN_BODY_LENGTH = int(os.getenv("SPEC_MIN_BODY_LENGTH", "300"))
SPEC_REQUIRED_SECTIONS = ["## Background", "## What to Build", "## Acceptance Criteria"]
SPEC_MIN_AC_ITEMS = int(os.getenv("SPEC_MIN_AC_ITEMS", "3"))

# Configured repositories for multi-repo dispatch
_SECONDARY_REPOS_RAW = [r.strip() for r in os.getenv("SECONDARY_REPOS", "").split(",") if r.strip()]
SECONDARY_REPOS: list[tuple[str, str]] = []
for _entry in _SECONDARY_REPOS_RAW:
    if ":" in _entry:
        _repo, _path = _entry.split(":", 1)
        SECONDARY_REPOS.append((_repo.strip(), _path.strip()))
    else:
        SECONDARY_REPOS.append((_entry, WO_PATH))

FACTORY_CONFIG_PATH = Path(os.getenv("FACTORY_CONFIG_PATH", "/config/factory-config.json"))


def _get_configured_repos() -> list[dict]:
    """Return all active configured repositories with their wo_path and plan_path."""
    repos: list[dict] = []
    seen: set[str] = set()

    # 1. Primary GITHUB_REPO
    if GITHUB_REPO:
        repos.append({
            "repo": GITHUB_REPO,
            "label": GITHUB_REPO.split("/")[-1],
            "wo_path": WO_PATH,
            "plan_path": PLAN_PATH,
            "primary": True,
        })
        seen.add(GITHUB_REPO)

    # 2. From factory-config.json if present
    if FACTORY_CONFIG_PATH.exists():
        try:
            cfg = json.loads(FACTORY_CONFIG_PATH.read_text())
            for p in cfg.get("projects", []):
                r = p.get("repo", "").strip()
                if r and r not in seen:
                    repos.append({
                        "repo": r,
                        "label": p.get("label", r.split("/")[-1]),
                        "wo_path": p.get("wo_path", WO_PATH),
                        "plan_path": p.get("plan_path", PLAN_PATH),
                        "primary": False,
                    })
                    seen.add(r)
        except Exception as exc:
            print(f"[orchestrator] config load failed: {exc}")

    # 3. From SECONDARY_REPOS env var fallback
    for _r, _p in SECONDARY_REPOS:
        if _r not in seen:
            repos.append({
                "repo": _r,
                "label": _r.split("/")[-1],
                "wo_path": _p or WO_PATH,
                "plan_path": PLAN_PATH,
                "primary": False,
            })
            seen.add(_r)

    return repos
RUNS_PATH = os.getenv("RUNS_PATH", "docs/factory/runs")
PLAN_PATH = os.getenv("PLAN_PATH", "docs/factory/PLAN.json")
# When set, WO specs / PLAN.json / branches are read from the local filesystem
# instead of GitHub API — dramatically reduces API call volume.
LOCAL_REPO_MOUNT = os.getenv("LOCAL_REPO_MOUNT", "")
DAILY_SUMMARY_HOUR = os.getenv("DAILY_SUMMARY_HOUR", "")
SUMMARY_ISSUE_NUMBER = os.getenv("SUMMARY_ISSUE_NUMBER", "")

STUCK_THRESHOLDS: dict[str, timedelta] = {
    "P0": timedelta(hours=4),
    "P1": timedelta(hours=12),
    "P2": timedelta(hours=24),
    "P3": timedelta(hours=48),
}
REVIEW_WAIT_THRESHOLDS: dict[str, timedelta] = {
    "P0": timedelta(hours=8),
    "P1": timedelta(hours=48),
    "P2": timedelta(hours=72),
}
API_PORT = int(os.getenv("API_PORT", "8100"))

DATA_DIR = Path("/data")
OUTPUT_PATH = DATA_DIR / "orchestrator.json"
DISPATCH_STATE_PATH = DATA_DIR / "dispatch_state.json"
VALIDATIONS_PATH = DATA_DIR / "pending_validations.json"
INTELLIGENCE_STATE_PATH = DATA_DIR / "intelligence_last_run.json"
WATCHDOG_PATH = Path(os.getenv("WATCHDOG_PATH", "/watchdog/watchdog.json"))
DB_PATH = DATA_DIR / "factory.db"


def _db():
    return _db_connect(DB_PATH)

_last_summary_day: int = -1
_last_intelligence_run: dict = {}

# ── In-memory state (persisted to volume) ────────────────────────────────────

_dispatch_state: dict[str, dict] = {}   # wo_id → claim record
_validations: list[dict] = []           # pending human validations
_orchestrator_output: dict = {}         # last poll snapshot
_held_wos: set[str] = set()            # WO IDs on hold (skip, don't claim)
_specs_cache: dict[int, dict] = {}     # all merged WO specs from last poll (primary + secondary)
_pm_dispatch: dict | None = None       # PM-requested direct dispatch {wo, backend, title}
_plan_overlay: list[dict] = []         # spec-file WOs not in PLAN.json — runtime-only, never written to disk
_approval_skips: dict[str, str] = {}   # wo_id → ISO timestamp until approval is bypassed
# WOs a human has explicitly approved this session, independent of dispatch
# state. The approval gate used to key off _dispatch_state[wo_id]["status"]
# == "approved" alone — but claim_wo pops that entry the moment the claim
# proceeds, and a transient failure shortly after (e.g. a container rebuild
# hiccup) resets the entry via release_dispatch, wiping every trace that a
# human already signed off. The WO then falls straight back into
# pending_approval on its very next claim attempt, forcing a second approval
# for a risk decision that hasn't actually changed. Cleared on completion or
# manual reset — see complete_wo() and reset_dispatch().
_wo_ever_approved: set[str] = set()
_preflight_held: dict[str, dict] = {}  # wo_id → {hold_reason, held_at, last_checked}
_max_retry_notified: set[str] = set()  # wo_ids already alerted for exceeding MAX_RETRY_ATTEMPTS
# Stall detection: the dispatch queue can end up non-empty but fully held (manually
# or auto-held) with nothing active — runners then poll /api/next forever getting
# "queue empty or all candidates claimed/blocked" with no one ever finding out. This
# ran silently for ~36h once (all 5 queued WOs held, wos_active=0) before a human
# noticed. _stall_since is set the first poll cycle the condition is seen and cleared
# the moment it isn't; _stall_alerted ensures one alert per stall episode, not one per
# poll cycle. In-memory only (like _last_summary_day) — an orchestrator restart at the
# exact wrong moment costs at most one missed detection cycle, not worth persisting for.
_stall_since: str | None = None
_stall_alerted: bool = False
STALL_ALERT_THRESHOLD_SECONDS = int(os.getenv("STALL_ALERT_THRESHOLD_SECONDS", "7200"))
# Last-good open-PR occupancy cache. Updated each poll; never cleared on fetch
# failure so a GitHub blip cannot reopen WOs that already have PRs.
_open_pr_wos: set[int] = set()
_open_pr_urls: dict[int, str] = {}
# Extra depends_on written by conflict_advisor (not the spec file).
_advisor_depends: dict[str, list[int]] = {}

HOLD_PATH = DATA_DIR / "held_wos.json"
PAUSE_PATH = DATA_DIR / "factory_paused.json"
ATTEMPTS_PATH = DATA_DIR / "attempt_counts.json"
PM_MEMORY_PATH = DATA_DIR / "pm_memory.json"
OVERRIDES_PATH = DATA_DIR / "wo_overrides.json"
RESERVED_WOS_PATH = DATA_DIR / "reserved_wos.json"
ADVISOR_PATH = DATA_DIR / "conflict_advisor.json"
RUNNERS_PATH = DATA_DIR / "runner_tokens.json"
RESERVATION_TTL_HOURS = 1

_pm_memory: dict = {}   # persisted PM preferences, decisions, dispatched history
_overrides: dict[str, dict] = {}  # WO-NNN → {"action": "no-auto-complete", ...}
_reserved: dict[str, dict[int, dict]] = {}   # repo → WO number → {reserved_by, reserved_at, title}
_runners: list[dict] = []  # registered agent runner tokens

_factory_paused: bool = False   # when True, get_next() returns null — drains gracefully
_attempt_counts: dict[str, int] = {}  # WO id → claims; survives DELETE /api/dispatch (AF-21)

# ── In-memory log buffer (replaces file-tail SSE — Docker volume mount lag) ───
_LOG_BUFFER_MAX = 2000
_log_buffer: list[str] = []            # circular buffer of log lines
_log_subscribers: list[asyncio.Queue] = []  # one Queue per active SSE client


import runner_auth


def _load_runners() -> None:
    global _runners
    _runners = runner_auth.load_runners(RUNNERS_PATH)


def _save_runners() -> None:
    runner_auth.save_runners(RUNNERS_PATH, _runners)


def _find_runner_by_token(token: str) -> dict | None:
    return runner_auth.find_runner_by_token(_runners, token)


def _load_state() -> None:
    global _dispatch_state, _validations, _held_wos, _factory_paused, _last_intelligence_run, _attempt_counts
    _init_db()
    _migrate_plan_json_to_db()
    # Load dispatch state: SQLite primary, JSON fallback (migration path)
    db_runs = _db_load_all_runs()
    if db_runs:
        _dispatch_state = db_runs
        _db_remember_runs(_dispatch_state)
        print(f"[orchestrator] loaded {len(db_runs)} dispatch entries from SQLite")
        # runs SQLite historically omitted claim_token. Recreating the
        # container then 409'd every heartbeat and the runner stopped
        # checkins, so the stale-claim sweep would reap a still-live agent.
        _restore_claim_tokens_from_json()
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
    _factory_paused = dispatch_control.load_pause(PAUSE_PATH)["paused"]
    _attempt_counts = dispatch_control.load_attempt_counts(ATTEMPTS_PATH)
    if INTELLIGENCE_STATE_PATH.exists():
        try:
            _last_intelligence_run = json.loads(INTELLIGENCE_STATE_PATH.read_text())
        except Exception:
            _last_intelligence_run = {}
    _load_overrides()
    _load_reserved()
    _load_advisor_depends()
    _load_runners()


def _load_overrides() -> None:
    global _overrides
    if OVERRIDES_PATH.exists():
        try:
            _overrides = json.loads(OVERRIDES_PATH.read_text())
        except Exception:
            _overrides = {}


def _save_overrides() -> None:
    try:
        dispatch_control.atomic_write_json(OVERRIDES_PATH, _overrides)
    except Exception as e:
        print(f"[orchestrator] overrides save failed: {e}")


def _is_overridden(wo_id: str, action: str) -> bool:
    return _overrides.get(wo_id, {}).get("action") == action


def _load_reserved() -> None:
    """Load persisted reservations, keyed by repo.

    Migrates the pre-multi-repo flat format ({"1035": {...}}) to the current
    nested one ({"dentroio/clarion": {"1035": {...}}}) — detected by whether
    the top-level keys look like repo names (contain "/") or bare numbers.
    """
    global _reserved
    if not RESERVED_WOS_PATH.exists():
        return
    try:
        raw = json.loads(RESERVED_WOS_PATH.read_text())
    except Exception:
        _reserved = {}
        return
    if raw and all("/" not in k for k in raw):
        raw = {GITHUB_REPO: raw}
    _reserved = {repo: {int(k): v for k, v in bucket.items()} for repo, bucket in raw.items()}


def _save_reserved() -> None:
    try:
        payload = {repo: {str(k): v for k, v in bucket.items()} for repo, bucket in _reserved.items()}
        dispatch_control.atomic_write_json(RESERVED_WOS_PATH, payload)
    except Exception as e:
        print(f"[orchestrator] reserved_wos save failed: {e}")


def _expire_stale_reservations() -> None:
    """Remove reservations older than RESERVATION_TTL_HOURS, across all repos."""
    cutoff = datetime.now(UTC) - timedelta(hours=RESERVATION_TTL_HOURS)
    changed = False
    for repo, bucket in list(_reserved.items()):
        stale = [
            num for num, meta in bucket.items()
            if datetime.fromisoformat(meta.get("reserved_at", "2000-01-01T00:00:00+00:00")) < cutoff
        ]
        for num in stale:
            del bucket[num]
            changed = True
        if not bucket:
            del _reserved[repo]
    if changed:
        _save_reserved()


def _next_wo_number() -> int:
    """Next available number for the default repo (GITHUB_REPO/WO_PATH).

    Synchronous — used by internal callers (intelligence loop, claim-reserve
    consume) that only ever number the primary repo's WOs. For any other
    repo, use `_next_wo_number_for`, which can scan via the GitHub API.
    """
    known: set[int] = set(_reserved.get(GITHUB_REPO, {}))
    if LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / WO_PATH
        if wo_dir.is_dir():
            for f in wo_dir.glob("WO-*.md"):
                n = _parse_wo_number(f.name)
                if n:
                    known.add(n)
    # Include dispatch state WO numbers, but only for entries still in flight.
    # Completed entries don't need protecting — if they landed a spec file
    # it's already in the scan above; if not (e.g. one-off process/conflict-
    # resolution WOs dispatched without ever writing a spec), they're
    # historical noise that would otherwise permanently inflate "next" past
    # whatever high-water mark they happened to use.
    for wo_id, meta in _dispatch_state.items():
        if isinstance(meta, dict) and meta.get("status") == "complete":
            continue
        try:
            known.add(int(wo_id.replace("WO-", "")))
        except ValueError:
            pass
    return (max(known) + 1) if known else 1000


async def _next_wo_number_for(client: httpx.AsyncClient, repo: str, wo_path: str) -> int:
    """Next available number for an arbitrary repo/wo_path.

    Deliberately does *not* reuse `_fetch_wo_specs` — that fetches and parses
    the full content of every WO file (title, status, priority...), which for
    a repo the size of agentic-factory's own docs/work_orders/ is 50+ GitHub
    API calls and blew past callers' timeouts (status-site's 5s reservation
    call). All we need here is filenames, so a single directory-listing call
    (same approach as github_writer.next_wo_number's API fallback) suffices.
    """
    if repo == GITHUB_REPO:
        return _next_wo_number()
    known: set[int] = set(_reserved.get(repo, {}))
    if LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / wo_path
        if wo_dir.is_dir():
            for f in wo_dir.glob("WO-*.md"):
                n = _parse_wo_number(f.name)
                if n:
                    known.add(n)
            return (max(known) + 1) if known else 1000
    try:
        items = await _get(client, f"/repos/{repo}/contents/{wo_path}")
        for item in items:
            if item.get("type") == "file":
                n = _parse_wo_number(item["name"])
                if n:
                    known.add(n)
    except Exception as e:
        print(f"[orchestrator] _next_wo_number_for failed for {repo}: {e}")
    return (max(known) + 1) if known else 1000


def _load_pm_memory() -> None:
    global _pm_memory
    if PM_MEMORY_PATH.exists():
        try:
            _pm_memory = json.loads(PM_MEMORY_PATH.read_text())
        except Exception:
            _pm_memory = {}


def _save_pm_memory() -> None:
    try:
        dispatch_control.atomic_write_json(PM_MEMORY_PATH, _pm_memory)
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


def _restore_claim_tokens_from_json() -> None:
    """Copy claim_token from the JSON backup when SQLite loaded without one."""
    if not DISPATCH_STATE_PATH.exists():
        return
    try:
        json_state = json.loads(DISPATCH_STATE_PATH.read_text())
    except Exception:
        return
    restored = 0
    for wo_id, entry in _dispatch_state.items():
        if entry.get("claim_token"):
            continue
        token = (json_state.get(wo_id) or {}).get("claim_token")
        if token:
            entry["claim_token"] = token
            restored += 1
    if restored:
        print(f"[orchestrator] restored {restored} claim token(s) from JSON backup")


def _save_dispatch() -> None:
    # JSON backup for other processes that may read the volume directly
    try:
        dispatch_control.atomic_write_json(DISPATCH_STATE_PATH, _dispatch_state)
    except Exception as e:
        print(f"[orchestrator] dispatch JSON backup failed: {e}")
    _db_sync_dispatch()


def _save_held() -> None:
    dispatch_control.atomic_write_json(HOLD_PATH, sorted(_held_wos))


def _load_advisor_depends() -> None:
    global _advisor_depends
    if not ADVISOR_PATH.exists():
        _advisor_depends = {}
        return
    try:
        raw = json.loads(ADVISOR_PATH.read_text(encoding="utf-8"))
        cleaned: dict[str, list[int]] = {}
        if isinstance(raw, dict):
            for wo_id, nums in raw.items():
                if not isinstance(nums, list):
                    continue
                cleaned[str(wo_id)] = [int(n) for n in nums if str(n).isdigit() or isinstance(n, int)]
        _advisor_depends = cleaned
    except Exception:
        _advisor_depends = {}


def _save_advisor_depends() -> None:
    try:
        dispatch_control.atomic_write_json(ADVISOR_PATH, _advisor_depends)
    except Exception as e:
        print(f"[orchestrator] conflict advisor save failed: {e}")


def _apply_advisor_edge(later: str, earlier: int, reason: str) -> None:
    deps = _advisor_depends.setdefault(later, [])
    if earlier not in deps:
        deps.append(earlier)
        _save_advisor_depends()
    thread_store.append_message(later, thread_store.system_message(
        f"🔀 Conflict advisor: wait for **WO-{earlier}** — {reason}"
    ))
    print(f"[orchestrator] advisor edge {later} → WO-{earlier} ({reason})")


def _effective_depends(wo: dict) -> list[int]:
    """Spec depends_on plus advisor edges (ints)."""
    wo_id = wo.get("wo", "")
    nums: list[int] = []
    seen: set[int] = set()
    extra = _advisor_depends.get(wo_id, []) if wo_id else []
    for d in list(wo.get("depends_on") or []) + list(extra):
        if isinstance(d, int):
            n = d
        else:
            n = occupancy.wo_num_from_id(str(d))
            if n is None:
                try:
                    n = int(str(d).replace("WO-", "").replace("wo-", ""))
                except ValueError:
                    continue
        if n not in seen:
            seen.add(n)
            nums.append(n)
    return nums


def _save_validations() -> None:
    dispatch_control.atomic_write_json(VALIDATIONS_PATH, _validations)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _lease_token(request: Request, body_token: str = "") -> str:
    return (request.headers.get("X-Factory-Claim-Token") or body_token or "").strip()


def _require_lease(wo_id: str, token: str) -> dict:
    """AF-18: mutating calls for an in-flight WO must present the claim token."""
    entry = _dispatch_state.get(wo_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"{wo_id} not claimed")
    stored = entry.get("claim_token")
    if not dispatch_control.lease_matches(stored, token):
        raise HTTPException(
            status_code=409,
            detail=f"{wo_id} claim lease mismatch — this agent no longer holds the claim",
        )
    return entry


def _refuse_if_paused() -> None:
    if _factory_paused:
        raise HTTPException(
            status_code=423,
            detail="factory paused — drain mode active, no new claims",
        )


def _public_dispatch_entry(entry: dict) -> dict:
    public = dict(entry)
    public.pop("claim_token", None)
    return public


# ── Pre-flight environment validation ────────────────────────────────────────

def _parse_requires_from_spec(spec: dict) -> dict:
    """Parse the ## Requirements fenced YAML block from a WO spec's raw body.

    Returns a dict like:
      {"connectors": [{"type": "palo_alto", "min_count": 1}], "services": ["data-service"]}
    Returns {} if no ## Requirements section or no `requires:` key found.
    """
    body = spec.get("_raw_body", "")
    # Find the ## Requirements section
    req_match = re.search(r"^## Requirements\s*\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    if not req_match:
        return {}
    section = req_match.group(1)
    # Extract content of the first fenced code block in that section
    fence_match = re.search(r"```(?:yaml)?\s*\n(.*?)```", section, re.DOTALL)
    if not fence_match:
        return {}
    yaml_text = fence_match.group(1)
    # Check that it has a requires: key
    if "requires:" not in yaml_text:
        return {}
    result: dict = {}
    # Parse connectors
    in_connectors = False
    connectors: list[dict] = []
    cur_connector: dict = {}
    in_services = False
    services: list[str] = []
    for line in yaml_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("connectors:"):
            in_connectors = True
            in_services = False
            continue
        if stripped.startswith("services:"):
            if cur_connector:
                connectors.append(cur_connector)
                cur_connector = {}
            in_services = True
            in_connectors = False
            continue
        if stripped and not stripped.startswith("#") and not stripped.startswith("requires:") and not stripped.startswith("clarion_"):
            if in_connectors:
                if stripped.startswith("- type:"):
                    if cur_connector:
                        connectors.append(cur_connector)
                    cur_connector = {"type": stripped.split(":", 1)[1].strip()}
                elif stripped.startswith("- connector_type:"):
                    if cur_connector:
                        connectors.append(cur_connector)
                    cur_connector = {"type": stripped.split(":", 1)[1].strip()}
                elif stripped.startswith("min_count:"):
                    cur_connector["min_count"] = int(stripped.split(":", 1)[1].strip())
                elif stripped.startswith("-") and not stripped.startswith("- type") and not stripped.startswith("- connector"):
                    in_connectors = False
            if in_services:
                if stripped.startswith("- ") and not stripped.startswith("- {"):
                    services.append(stripped[2:].strip())
                elif not stripped.startswith("-"):
                    in_services = False
    if cur_connector:
        connectors.append(cur_connector)
    if connectors:
        result["connectors"] = connectors
    if services:
        result["services"] = services
    return result


async def _query_clarion_connectors(connector_type: str) -> int:
    """Query Clarion API for number of connected connectors of the given type.
    Returns 0 on any error (fail-safe: treat unavailable Clarion as no connectors).
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{CLARION_API_URL}/api/connectors",
                params={"type": connector_type, "status": "connected"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return len(data)
                if isinstance(data, dict):
                    return len(data.get("connectors", data.get("items", [])))
    except Exception as e:
        print(f"[preflight] Clarion API query failed for connector type '{connector_type}': {e}")
    return 0


async def preflight_check(requires: dict) -> list[str]:
    """Check WO environment requirements. Returns list of unmet conditions (empty = OK)."""
    if not requires:
        return []
    failures: list[str] = []
    for req in requires.get("connectors", []):
        ctype = req.get("type") or req.get("connector_type", "")
        min_count = req.get("min_count", 1)
        if not ctype:
            continue
        count = await _query_clarion_connectors(ctype)
        if count < min_count:
            failures.append(f"connector '{ctype}': need {min_count} connected, found {count}")
    for svc in requires.get("services", []):
        # For now, all Clarion services are assumed healthy (we can extend this
        # with docker compose ps checks if the orchestrator has access).
        # This is best-effort — service checks are advisory, not blocking.
        pass
    return failures


# ── SQLite persistence ────────────────────────────────────────────────────────

def _init_db() -> None:
    with _db() as conn:
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
              pr_number INTEGER,
              attempt_count INTEGER DEFAULT 0,
              first_claimed_at TEXT,
              retried_at TEXT,
              stuck INTEGER DEFAULT 0,
              stuck_since TEXT
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
              files_likely_changed TEXT DEFAULT '[]',
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
        # CREATE TABLE IF NOT EXISTS is a no-op on an already-existing table —
        # it does not add new columns. Migrate existing databases explicitly.
        try:
            conn.execute("ALTER TABLE queue ADD COLUMN files_likely_changed TEXT DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # column already exists
        # runs table predates attempt_count/first_claimed_at/retried_at/stuck/stuck_since —
        # without these, every restart silently drops them (_db_sync_dispatch only wrote the
        # original columns), resetting the max-retry counter and stuck-detection state.
        for _col, _ddl in (
            ("attempt_count", "ALTER TABLE runs ADD COLUMN attempt_count INTEGER DEFAULT 0"),
            ("first_claimed_at", "ALTER TABLE runs ADD COLUMN first_claimed_at TEXT"),
            ("retried_at", "ALTER TABLE runs ADD COLUMN retried_at TEXT"),
            ("stuck", "ALTER TABLE runs ADD COLUMN stuck INTEGER DEFAULT 0"),
            ("stuck_since", "ALTER TABLE runs ADD COLUMN stuck_since TEXT"),
            ("claim_token", "ALTER TABLE runs ADD COLUMN claim_token TEXT DEFAULT ''"),
        ):
            try:
                conn.execute(_ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
    _db_init_history_table(DB_PATH)


def _db_load_all_runs() -> dict[str, dict]:
    try:
        with _db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM runs").fetchall()
            return {row["wo"]: dict(row) for row in rows}
    except Exception:
        return {}


def _db_sync_dispatch() -> None:
    """Snapshot dispatch state and persist it. Off the event loop when one is running."""
    snapshot = {
        wo_id: dict(record) if isinstance(record, dict) else record
        for wo_id, record in _dispatch_state.items()
    }
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _db_sync_runs(DB_PATH, snapshot)
        return
    _db_schedule_sync_runs(DB_PATH, snapshot)


def _db_append_step(wo_id: str, status: str, step: str = "", agent: str = "") -> None:
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO run_steps (wo, ts, status, step, agent) VALUES (?, ?, ?, ?, ?)",
                (wo_id, _utcnow(), status, step, agent),
            )
    except Exception as e:
        print(f"[db] append_step failed for {wo_id}: {e}")


# ── Queue / phases / milestones DB helpers ────────────────────────────────────

def _db_get_queue() -> list[dict]:
    try:
        with _db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM queue ORDER BY position ASC, added_at ASC").fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["pin"] = bool(d.get("pin", 0))
                d["blocks_milestones"] = json.loads(d.get("blocks_milestones") or "[]")
                d["depends_on"] = json.loads(d.get("depends_on") or "[]")
                d["files_likely_changed"] = json.loads(d.get("files_likely_changed") or "[]")
                result.append(d)
            return result
    except Exception:
        return []


def _db_get_phases() -> list[dict]:
    try:
        with _db() as conn:
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
        with _db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM milestones").fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _db_get_programs() -> list[dict]:
    try:
        with _db() as conn:
            rows = conn.execute("SELECT id, label, description, added_at FROM programs ORDER BY label").fetchall()
        return [{"id": r[0], "label": r[1], "description": r[2], "added_at": r[3]} for r in rows]
    except Exception:
        return []


def _db_upsert_program(id_: str, label: str, description: str = "") -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO programs (id, label, description) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET label=excluded.label, description=excluded.description",
            (id_, label, description),
        )
        conn.commit()


def _db_delete_program(id_: str) -> bool:
    with _db() as conn:
        cur = conn.execute("DELETE FROM programs WHERE id = ?", (id_,))
        conn.commit()
    return cur.rowcount > 0


def _db_get_queue_wo_ids() -> set[str]:
    try:
        with _db() as conn:
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
        with _db() as conn:
            placeholders = ",".join("?" * len(done_wo_ids))
            cur = conn.execute(f"DELETE FROM queue WHERE wo IN ({placeholders})", list(done_wo_ids))
            conn.commit()
            return cur.rowcount
    except Exception as e:
        print(f"[db] remove_done_wos failed: {e}")
        return 0


def _db_upsert_queue_entry(entry: dict) -> None:
    try:
        with _db() as conn:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM queue").fetchone()[0]
            conn.execute("""
                INSERT INTO queue
                  (wo, title, phase, priority, effort, position, pin,
                   blocks_milestones, depends_on, files_likely_changed, notes, docs_required)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wo) DO UPDATE SET
                  title=excluded.title, phase=excluded.phase, priority=excluded.priority,
                  effort=excluded.effort, pin=excluded.pin,
                  blocks_milestones=excluded.blocks_milestones,
                  depends_on=excluded.depends_on, files_likely_changed=excluded.files_likely_changed,
                  notes=excluded.notes, docs_required=excluded.docs_required
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
                json.dumps(entry.get("files_likely_changed", [])),
                entry.get("notes", ""),
                entry.get("docs_required", "[]"),
            ))
            conn.commit()
    except Exception as e:
        print(f"[db] upsert_queue_entry failed for {entry.get('wo')}: {e}")


def _db_upsert_phase(phase: dict) -> None:
    try:
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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

    # Startup orphan check: warn about DB entries with no matching spec file.
    if LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / WO_PATH
        if wo_dir.is_dir():
            spec_wos = {f"WO-{_parse_wo_number(f.name)}" for f in wo_dir.glob("WO-*.md") if _parse_wo_number(f.name)}
            try:
                with _db() as conn:
                    db_wos = {r[0] for r in conn.execute("SELECT wo FROM queue").fetchall()}
                orphans = db_wos - spec_wos
                if orphans:
                    print(f"[orchestrator] WARNING: {len(orphans)} DB queue entries have no spec file: {sorted(orphans)}")
            except Exception:
                pass


def _writeback_plan_json(new_entries: list[dict]) -> None:
    """Append newly-discovered spec-file WOs to PLAN.json so humans can see them.

    Only appends WOs not already in the file. Never overwrites human-set fields.
    Skips silently on any error — write-back is advisory, not critical.
    """
    if not new_entries or not LOCAL_REPO_MOUNT:
        return
    plan_path = Path(LOCAL_REPO_MOUNT) / PLAN_PATH
    if not plan_path.exists():
        return
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        existing = {e["wo"] for e in plan.get("queue", [])}
        added = []
        for entry in new_entries:
            if entry["wo"] in existing:
                continue
            plan.setdefault("queue", []).append({
                "wo": entry["wo"],
                "title": entry.get("title", entry["wo"]),
                "phase": entry.get("phase", "backlog"),
                "priority": entry.get("priority", "P2"),
                "effort": entry.get("effort", ""),
                "blocks_milestones": [],
                "depends_on": entry.get("depends_on", []),
                "pin": False,
                "notes": "Auto-discovered from spec file.",
            })
            existing.add(entry["wo"])
            added.append(entry["wo"])
        if added:
            plan["last_updated"] = datetime.now(UTC).strftime("%Y-%m-%d")
            plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"[orchestrator] PLAN.json write-back: added {added}")
    except Exception as e:
        print(f"[orchestrator] PLAN.json write-back failed (non-fatal): {e}")


# ── Pydantic models ───────────────────────────────────────────────────────────

class ClaimRequest(BaseModel):
    wo: str           # e.g. "WO-359"
    agent: str        # agent runner name e.g. "claude-runner"
    backend: str = "" # actual AI backend: "claude" | "cursor" | "codex" | "gemini"
    workstation: str = ""
    slug: str = ""


class ParkRequest(BaseModel):
    status: str = "awaiting_commit"
    reason: str = ""
    claim_token: str = ""


class CompleteRequest(BaseModel):
    wo: str
    agent: str = ""
    pr_url: str = ""
    pr_number: int | None = None
    claim_token: str = ""


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
    claim_token: str = ""


class CodexDispatchRequest(BaseModel):
    wo: str
    repo: str = ""
    ref: str = "main"
    slug: str = ""


class RegisterRunnerRequest(BaseModel):
    agent_name: str
    backend: str = "claude"
    workstation: str = ""


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


# ── Intelligence loop ─────────────────────────────────────────────────────────

async def _intelligence_job() -> None:
    global _last_intelligence_run
    print("[intelligence] running pass…")

    def _enqueue(entry: dict) -> None:
        _db_upsert_queue_entry(entry)

    def _update_dispatch(wo_id: str, patch: dict) -> None:
        if wo_id in _dispatch_state:
            _dispatch_state[wo_id].update(patch)
            _save_dispatch()

    def _reserve_wo(title: str) -> str:
        _expire_stale_reservations()
        num = _next_wo_number()
        _reserved.setdefault(GITHUB_REPO, {})[num] = {
            "reserved_by": "intelligence-loop",
            "reserved_at": _utcnow(),
            "title": title,
        }
        _save_reserved()
        return f"WO-{num}"

    try:
        result = await _intel.run_intelligence_pass(
            github_token=_get_github_token(),
            github_repo=GITHUB_REPO,
            anthropic_key=_get_anthropic_key(),
            dispatch_state=dict(_dispatch_state),
            enqueue_wo=_enqueue,
            update_dispatch=_update_dispatch,
            reserve_wo=_reserve_wo,
        )
        try:
            advisor = await _run_conflict_advisor()
            result.setdefault("actions_taken", []).extend(advisor.get("actions") or [])
            result["conflict_advisor"] = {
                k: advisor[k]
                for k in ("edges_added", "deterministic", "llm", "open_wos_considered")
                if k in advisor
            }
        except Exception as adv_err:
            result.setdefault("actions_taken", []).append(f"conflict advisor failed: {adv_err}")
            print(f"[intelligence] conflict advisor failed: {adv_err}")
        _last_intelligence_run = result
        try:
            dispatch_control.atomic_write_json(INTELLIGENCE_STATE_PATH, result)
        except Exception:
            pass
        if result.get("actions_taken"):
            print(f"[intelligence] actions taken: {result['actions_taken']}")
        else:
            print(f"[intelligence] pass complete — no actions needed")
    except Exception as e:
        _last_intelligence_run = {"error": str(e), "started_at": datetime.now(UTC).isoformat()}
        try:
            dispatch_control.atomic_write_json(INTELLIGENCE_STATE_PATH, _last_intelligence_run)
        except Exception:
            pass
        print(f"[intelligence] pass failed: {e}")


async def _run_conflict_advisor() -> dict:
    """Queue hygiene: extra depends_on edges. Does not pick the next WO."""
    open_wos: list[dict] = []
    inflight = {"claimed", "in_progress", "awaiting_human", "awaiting_commit", "pending_approval"}
    for num, spec in (_specs_cache or {}).items():
        if spec.get("repo", GITHUB_REPO) != GITHUB_REPO:
            continue
        if _is_done(spec.get("status", "")) or _is_blocked(spec.get("status", "")):
            continue
        wo_id = f"WO-{num}"
        if wo_id in _held_wos:
            continue
        if (_dispatch_state.get(wo_id) or {}).get("status") in inflight:
            continue
        open_wos.append({
            "wo": wo_id,
            "number": num,
            "title": spec.get("title", wo_id),
            "priority": spec.get("priority", "P2"),
            "services": spec.get("services") or [],
            "files_likely_changed": spec.get("files_likely_changed") or [],
            "depends_on": spec.get("depends_on") or [],
            "_raw_body": spec.get("_raw_body", ""),
        })
    return await conflict_advisor.run_advisor_pass(
        open_wos,
        _advisor_depends,
        anthropic_key=_get_anthropic_key(),
        apply_edge=_apply_advisor_edge,
    )


# ── FastAPI app + lifespan ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    thread_store.THREADS_DIR.mkdir(parents=True, exist_ok=True)
    _load_state()
    _load_pm_memory()
    await _init_secrets()

    # _init_secrets() just ran, so Vault-only tokens are already loadable here —
    # check via _get_github_token(), not the bare env-only constant, or a
    # dashboard-only (no .env) token would leave the scheduler permanently
    # disabled even across a restart. GITHUB_REPO has no such live-vs-static
    # distinction to fix: it's baked into dozens of function default-parameter
    # values throughout this file, evaluated once at import — changing it
    # legitimately still needs a restart, unlike a rotated token.
    if not _get_github_token() or not GITHUB_REPO:
        print("[orchestrator] WARNING: GITHUB_TOKEN or GITHUB_REPO not set — poll loop disabled")
    else:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(poll, "interval", seconds=POLL_INTERVAL)
        scheduler.add_job(_intelligence_job, "interval", seconds=INTELLIGENCE_INTERVAL)
        scheduler.add_job(_refresh_model_cache, "interval", seconds=600)
        scheduler.add_job(_refresh_agent_runner_url, "interval", seconds=60)
        scheduler.start()
        app.state.scheduler = scheduler
        # Fire first poll in background — store ref so it isn't GC'd
        app.state.initial_poll = asyncio.create_task(poll())
        app.state.initial_model_refresh = asyncio.create_task(_refresh_model_cache())
        app.state.initial_agent_runner_refresh = asyncio.create_task(_refresh_agent_runner_url())

    start_slack_bot(secrets=_load_secrets())

    yield

    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown()


app = FastAPI(title="Factory Orchestrator", lifespan=lifespan)

API_SECRET = os.getenv("API_SECRET", "")

# Fail closed: this port is meant to be loopback-only, but a misconfigured
# deploy (or a future change that widens the binding) must not silently run
# fully unauthenticated. AF-09 found this exact state live: API_SECRET was
# absent from the deployed .env, so every route — including GET /api/dispatch
# (full internal state) — was reachable with zero credentials.
if not API_SECRET:
    raise RuntimeError(
        "API_SECRET is not set. The orchestrator refuses to start without it — "
        "generate one (e.g. `python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"`) "
        "and set API_SECRET in .env."
    )


@app.middleware("http")
async def _bearer_auth(request: Request, call_next):
    """Require a bearer token on every request, GET included.

    Accepts either master API_SECRET or an active per-runner token (rn_...).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    token = auth[7:].strip()
    if not token:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    # 1. Master API_SECRET
    if _secrets_mod.compare_digest(token, API_SECRET):
        request.state.is_master = True
        request.state.runner = None
        return await call_next(request)

    # 2. Per-runner token
    runner = _find_runner_by_token(token)
    if runner and runner.get("status") == "active":
        runner["last_seen"] = _utcnow()
        _save_runners()
        request.state.is_master = False
        request.state.runner = runner
        return await call_next(request)

    return JSONResponse({"detail": "Unauthorized"}, status_code=401)


def _enforce_agent_identity(request: Request, agent_name: str) -> None:
    """If authenticated via a runner token, enforce that agent_name matches the registered identity."""
    runner = getattr(request.state, "runner", None)
    ok, err = runner_auth.check_agent_identity(runner, agent_name)
    if not ok:
        raise HTTPException(status_code=403, detail=err)


# Was allow_origins=["*"] — permitted any website the developer's browser
# visited to fetch() this port directly (it's loopback-bound, but browsers
# don't treat "same machine" as "same origin"). Nothing in this system's own
# UI calls the orchestrator directly from browser JS (status-site's Python
# backend proxies everything server-side), so there's no legitimate origin
# that needs this at all — restricting to status-site's own dev origins is
# defense in depth, not a functional requirement.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8099", "http://127.0.0.1:8099"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "repo": GITHUB_REPO}


@app.get("/api/intelligence/status")
async def get_intelligence_status():
    return JSONResponse(content=_last_intelligence_run or {"status": "not_run_yet"})


@app.post("/api/intelligence/run")
async def trigger_intelligence_run():
    asyncio.create_task(_intelligence_job())
    return JSONResponse(content={"ok": True, "message": "Intelligence pass triggered"})


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
async def get_next(domain: str = "", repo: str = ""):
    """Return the highest-priority unclaimed WO matching the optional domain and repo filter."""
    global _pm_dispatch
    if _factory_paused:
        return {"wo": None, "reason": "factory paused — drain mode active"}

    active_statuses = {"claimed", "in_progress", "awaiting_human", "awaiting_commit", "complete"}

    # PM-dispatched WO takes priority over the normal queue
    if _pm_dispatch:
        dispatch = _pm_dispatch
        wo_id = dispatch["wo"]
        occupied = _occupancy_reason_for(wo_id)
        if occupied:
            # Keep the PM request queued — occupancy can clear (PR merged,
            # claim file completed) and the next poll should still honor it.
            return {"wo": None, "reason": f"{wo_id} occupied — {occupied}"}
        _pm_dispatch = None
        existing = _dispatch_state.get(wo_id, {})
        if existing.get("status") in active_statuses - {"complete"}:
            return {"wo": None, "reason": f"{wo_id} already active"}
        spec = _specs_cache.get(int(wo_id.replace("WO-", "")), {}) if _specs_cache else {}
        target_repo = spec.get("repo", GITHUB_REPO)
        if repo and target_repo != repo:
            return {"wo": None, "reason": f"{wo_id} belongs to {target_repo}, not {repo}"}
        return {
            "wo": wo_id,
            "title": spec.get("title", dispatch.get("title", wo_id)),
            "priority": spec.get("priority", "P2"),
            "effort": spec.get("effort", "M"),
            "repo": target_repo,
            "wo_path": spec.get("wo_path", WO_PATH),
            "_dispatch_backend": dispatch.get("backend"),
        }

    plan = _orchestrator_output.get("plan", {})
    queue: list[dict] = plan.get("queue", [])

    # Audit F-02: this used to count every non-complete status — including
    # awaiting_human/awaiting_commit, which are WOs sitting idle waiting on a
    # human to review a PR, consuming zero CI/container resources.
    active_count = sum(
        1 for c in _dispatch_state.values()
        if c.get("status") in ("claimed", "in_progress")
    )
    if active_count >= MAX_PARALLEL_WOS:
        return {"wo": None, "reason": f"at capacity ({active_count}/{MAX_PARALLEL_WOS} active)"}

    domain_tokens = [t.lower() for t in domain.split(",") if t.strip()] if domain else []

    # Files currently being touched by whatever's actively claimed right now —
    # scoped by repository to avoid false collisions between different projects.
    files_by_wo = {w.get("wo", ""): set(w.get("files_likely_changed") or []) for w in queue}
    files_in_flight_by_repo: dict[str, set[str]] = {}
    services_in_flight_by_repo: dict[str, set[str]] = {}
    for active_id, active_entry in _dispatch_state.items():
        act_repo = active_entry.get("repo") or GITHUB_REPO
        if active_entry.get("status") in active_statuses - {"complete"}:
            files_in_flight_by_repo.setdefault(act_repo, set()).update(files_by_wo.get(active_id, set()))
        if active_entry.get("status") in ("claimed", "in_progress"):
            n = occupancy.wo_num_from_id(active_id)
            if n is not None:
                services_in_flight_by_repo.setdefault(act_repo, set()).update(
                    conflict_advisor.service_set_from_spec((_specs_cache or {}).get(n) or {})
                )

    for wo in queue:
        wo_id = wo.get("wo", "")
        if wo_id in _held_wos:
            continue
        if _is_done(wo.get("status", "")):
            continue
        cand_repo = wo.get("repo") or GITHUB_REPO
        if repo and cand_repo != repo:
            continue
        claim = _dispatch_state.get(wo_id, {})
        if _claim_blocks_next(wo_id, claim, _specs_cache or {}):
            continue
        occupied = _occupancy_reason_for(wo_id)
        if occupied:
            continue
        # A WO that already exceeded MAX_RETRY_ATTEMPTS will always 429 on
        # claim (see /api/claim below)
        if claim.get("attempt_count", 0) >= MAX_RETRY_ATTEMPTS:
            continue
        # Dependency enforcement — skip WOs whose depends_on aren't complete yet.
        deps = _effective_depends(wo)
        unmet = [d for d in deps if not _dependency_satisfied(d, _specs_cache or {}, _dispatch_state)]
        if unmet:
            continue
        # File-overlap guard — scoped to the candidate WO's target repository
        overlap = files_by_wo.get(wo_id, set()) & files_in_flight_by_repo.get(cand_repo, set())
        if overlap:
            continue
        # Same-service mutex — scoped to the candidate WO's target repository
        n = occupancy.wo_num_from_id(wo_id)
        cand_svcs = conflict_advisor.service_set_from_spec(
            (_specs_cache or {}).get(n or -1) or {}
        ) if n is not None else set()
        if cand_svcs & services_in_flight_by_repo.get(cand_repo, set()):
            continue
        # Domain filter — skip WOs not in this runner's domain
        if domain_tokens:
            wo_services = wo.get("services", "").lower()
            wo_priority = wo.get("priority", "").upper()
            docs_domain = any(t in ("docs", "p3") for t in domain_tokens)
            if docs_domain:
                if not ("none" in wo_services or "docs" in wo_services or wo_priority == "P3"):
                    continue
            else:
                if not any(t in wo_services for t in domain_tokens):
                    continue
        return {
            **wo,
            "repo": cand_repo,
            "wo_path": wo.get("wo_path", WO_PATH),
        }

    return {"wo": None, "reason": "queue empty or all candidates claimed/blocked"}


@app.post("/api/pm/dispatch")
async def pm_dispatch_wo(wo: str, backend: str = "claude"):
    """Store a PM-requested direct dispatch — picked up by the runner on next /api/next poll."""
    global _pm_dispatch
    _refuse_if_paused()
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
    dispatch_control.save_pause(PAUSE_PATH, True, "operator pause")
    return {"paused": True, "message": "Factory draining — no new WOs will be claimed"}


@app.post("/api/factory/resume")
async def resume_factory():
    """Allow the runner to claim new WOs again."""
    global _factory_paused
    _factory_paused = False
    dispatch_control.save_pause(PAUSE_PATH, False)
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


# ── Override tombstone API ────────────────────────────────────────────────────

class OverrideRequest(BaseModel):
    action: str  # e.g. "no-auto-complete"


@app.post("/api/wos/{wo_id}/override")
async def set_override(wo_id: str, req: OverrideRequest, request: Request):
    """Create or update a human override tombstone for a WO."""
    wo_id = wo_id.upper()
    _overrides[wo_id] = {
        "action": req.action,
        "set_by": "human",
        "set_at": _utcnow(),
    }
    _save_overrides()
    print(f"[orchestrator] override set: {wo_id} → {req.action}")
    return {"wo_id": wo_id, "override": _overrides[wo_id]}


@app.delete("/api/wos/{wo_id}/override")
async def delete_override(wo_id: str):
    """Remove a human override tombstone so normal automation resumes."""
    wo_id = wo_id.upper()
    removed = _overrides.pop(wo_id, None)
    if removed is None:
        raise HTTPException(status_code=404, detail=f"No override for {wo_id}")
    _save_overrides()
    print(f"[orchestrator] override removed: {wo_id}")
    return {"wo_id": wo_id, "removed": removed}


@app.get("/api/wos/{wo_id}/override")
async def get_override(wo_id: str):
    """Get the current override tombstone for a WO, or 404."""
    wo_id = wo_id.upper()
    override = _overrides.get(wo_id)
    if override is None:
        raise HTTPException(status_code=404, detail=f"No override for {wo_id}")
    return {"wo_id": wo_id, "override": override}


# ── WO Number Reservation API ─────────────────────────────────────────────────

class ReserveRequest(BaseModel):
    title: str = ""
    reserved_by: str = "unknown"
    # Defaults to GITHUB_REPO/WO_PATH (Clarion) when omitted — existing callers
    # are unaffected. Pass repo to number WOs in a different repo, e.g.
    # SECONDARY_REPOS entries like "dentroio/agentic-factory".
    repo: str | None = None
    wo_path: str | None = None


@app.post("/api/wos/reserve")
async def reserve_wo_number(req: ReserveRequest):
    """Atomically reserve the next WO number. Prevents concurrent number collisions."""
    _expire_stale_reservations()
    repo = req.repo or GITHUB_REPO
    wo_path = req.wo_path or WO_PATH
    async with httpx.AsyncClient(timeout=15) as client:
        num = await _next_wo_number_for(client, repo, wo_path)
    bucket = _reserved.setdefault(repo, {})
    bucket[num] = {
        "reserved_by": req.reserved_by,
        "reserved_at": _utcnow(),
        "title": req.title,
    }
    _save_reserved()
    return {"wo_id": f"WO-{num}", "number": num, "repo": repo, "reserved_at": bucket[num]["reserved_at"]}


@app.get("/api/wos/reserved")
async def list_reserved_wos(repo: str = GITHUB_REPO):
    """List currently active WO number reservations for a repo (defaults to GITHUB_REPO)."""
    _expire_stale_reservations()
    bucket = _reserved.get(repo, {})
    return {
        "repo": repo,
        "reserved": [
            {"number": num, "wo_id": f"WO-{num}", **meta}
            for num, meta in sorted(bucket.items())
        ]
    }


@app.post("/api/claim")
async def claim_wo(req: ClaimRequest, request: Request):
    """Atomically claim a WO. Returns 409 if already claimed by another agent."""
    _refuse_if_paused()
    _enforce_agent_identity(request, req.agent)
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

    occupied = _occupancy_reason_for(wo_id)
    if occupied:
        print(f"[orchestrator] {wo_id} claim refused — occupied: {occupied}")
        raise HTTPException(status_code=423, detail=f"{wo_id} occupied — {occupied}")

    if existing.get("status") in active_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"{wo_id} already claimed by {existing['agent']} on {existing.get('workstation', '?')}",
        )

    wo_num = int(wo_id.replace("WO-", "")) if wo_id.replace("WO-", "").isdigit() else -1
    wo_spec = _specs_cache.get(wo_num, {})

    # Pre-flight environment check — run before approval gate so unrunnable WOs are held early.
    if existing.get("status") != "preflight_held":
        requires = _parse_requires_from_spec(wo_spec)
        if requires:
            pf_failures = await preflight_check(requires)
            # preflight_check is the only await between the active_statuses
            # check above and the final claim write below — two requests for
            # the same wo_id can both pass that check before either finishes
            # awaiting here. Re-check with a fresh read: if the other request
            # already claimed it while we were awaiting, back off instead of
            # both believing they won.
            existing = _dispatch_state.get(wo_id, {})
            if existing.get("status") in active_statuses:
                raise HTTPException(
                    status_code=409,
                    detail=f"{wo_id} already claimed by {existing.get('agent')} on {existing.get('workstation', '?')} (lost the race during preflight check)",
                )
            if pf_failures:
                reason_str = "; ".join(pf_failures)
                _dispatch_state[wo_id] = {
                    **existing,
                    "wo": wo_id,
                    "slug": req.slug or existing.get("slug", ""),
                    "agent": req.agent,
                    "workstation": req.workstation,
                    "status": "preflight_held",
                    "hold_reason": pf_failures,
                    "held_at": _utcnow(),
                    "last_checked": _utcnow(),
                }
                _preflight_held[wo_id] = {
                    "hold_reason": pf_failures,
                    "held_at": _utcnow(),
                    "last_checked": _utcnow(),
                    "requires": requires,
                }
                _save_dispatch()
                thread_store.append_message(wo_id, thread_store.system_message(
                    f"🚫 {wo_id} held — environment requirements not met:\n"
                    + "\n".join(f"  • {f}" for f in pf_failures)
                    + "\n\nWill re-check every 30 minutes."
                ))
                asyncio.create_task(notify_factory_alert(
                    title=f"{wo_id} held — environment not ready",
                    body=reason_str,
                    level="warning",
                    source="preflight-check",
                    secrets=_load_secrets(),
                ))
                raise HTTPException(status_code=423, detail=f"{wo_id} held: {reason_str}")

    # Pre-dispatch approval gate: P1 WOs (and any in REQUIRE_APPROVAL_FOR) need human sign-off
    # unless already approved or skipped.
    wo_spec = _specs_cache.get(wo_num, {})
    wo_priority = wo_spec.get("priority", "P2")
    skip_entry = _approval_skips.get(wo_id)
    skip_active = skip_entry and datetime.now(UTC) < datetime.fromisoformat(skip_entry)
    already_approved = existing.get("status") == "approved" or wo_id in _wo_ever_approved
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

    prev = _dispatch_state.get(wo_id, {})
    attempt_count = dispatch_control.recorded_attempts(
        _attempt_counts, wo_id, prev.get("attempt_count", 0)
    ) + 1
    if attempt_count > MAX_RETRY_ATTEMPTS:
        if wo_id not in _max_retry_notified:
            _max_retry_notified.add(wo_id)
            thread_store.append_message(wo_id, thread_store.system_message(
                f"🛑 {wo_id} exceeded max retry attempts ({MAX_RETRY_ATTEMPTS}) — "
                f"blocked from further claims until manually reset."
            ))
            asyncio.create_task(notify_factory_alert(
                title=f"{wo_id} needs manual reset",
                body=f"Exceeded max retry attempts ({MAX_RETRY_ATTEMPTS}). "
                     f"POST /api/dispatch/{wo_id}/reset to clear and let the factory retry it.",
                level="urgent",
                source="max-retry-gate",
                secrets=_load_secrets(),
            ))
        raise HTTPException(
            status_code=429,
            detail=f"{wo_id} exceeded max retry attempts ({MAX_RETRY_ATTEMPTS}). "
                   "Use POST /api/dispatch/{wo_id}/reset to force-clear the attempt counter.",
        )

    # Consume reservation if one exists for this WO number (claims are always
    # against the primary repo — dispatch state doesn't track secondary repos)
    if wo_num in _reserved.get(GITHUB_REPO, {}):
        del _reserved[GITHUB_REPO][wo_num]
        _save_reserved()

    target_repo = wo_spec.get("repo") or GITHUB_REPO
    claim_token = dispatch_control.issue_claim_token()
    _dispatch_state[wo_id] = {
        "wo": wo_id,
        "slug": req.slug,
        "agent": req.agent,
        "backend": req.backend or req.agent,
        "workstation": req.workstation,
        "claimed_at": _utcnow(),
        "last_seen": _utcnow(),
        "status": "claimed",
        "pr_url": "",
        "attempt_count": attempt_count,
        "first_claimed_at": prev.get("first_claimed_at", _utcnow()),
        "claim_token": claim_token,
        "repo": target_repo,
    }
    dispatch_control.record_attempt(_attempt_counts, wo_id, attempt_count)
    dispatch_control.save_attempt_counts(ATTEMPTS_PATH, _attempt_counts)
    _save_dispatch()
    _db_append_step(wo_id, "claimed", agent=req.agent)
    thread_store.append_message(wo_id, thread_store.system_message(
        f"{wo_id} claimed by **{req.agent}** on `{req.workstation or 'unknown'}`"
    ))
    print(f"[orchestrator] {wo_id} claimed by {req.agent} on {req.workstation}")
    return {"ok": True, "wo": wo_id, "agent": req.agent, "claim_token": claim_token, "repo": target_repo}


@app.get("/api/factory/projects")
async def api_get_factory_projects():
    """Return list of all configured projects for multi-repo dispatch."""
    return {"ok": True, "projects": _get_configured_repos()}


@app.get("/api/runners")
async def list_runners():
    """List registered agent runner credentials (tokens masked)."""
    _load_runners()
    masked = []
    for r in _runners:
        masked.append({
            "id": r["id"],
            "agent_name": r["agent_name"],
            "backend": r.get("backend", "claude"),
            "workstation": r.get("workstation", ""),
            "token_prefix": r.get("token_prefix", "rn_..."),
            "status": r.get("status", "active"),
            "created_at": r.get("created_at"),
            "last_seen": r.get("last_seen"),
            "revoked_at": r.get("revoked_at"),
        })
    return {"ok": True, "runners": masked}


@app.post("/api/runners/register")
async def register_runner(req: RegisterRunnerRequest):
    """Provision a new token for an agent runner. Returns plaintext token once."""
    agent_name = req.agent_name.strip()
    if not agent_name:
        raise HTTPException(status_code=400, detail="agent_name required")
    _load_runners()
    try:
        runner_data = runner_auth.register_runner(
            RUNNERS_PATH,
            _runners,
            agent_name=agent_name,
            backend=req.backend or "claude",
            workstation=req.workstation or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    print(f"[orchestrator] registered new runner '{agent_name}' ({runner_data['id']})")
    return {"ok": True, "runner": runner_data}


@app.post("/api/runners/{runner_id}/revoke")
async def revoke_runner(runner_id: str):
    """Revoke an agent runner's token immediately."""
    _load_runners()
    target = runner_auth.revoke_runner(RUNNERS_PATH, _runners, runner_id)
    if not target:
        raise HTTPException(status_code=404, detail="Runner not found")
    print(f"[orchestrator] revoked runner token {runner_id} ('{target.get('agent_name')}')")
    return {"ok": True, "runner_id": runner_id, "status": "revoked"}


@app.post("/api/checkin")
async def checkin(request: Request, wo: str, agent: str, step: str = ""):
    """Agent heartbeat — update step label while working."""
    _enforce_agent_identity(request, agent)
    entry = _require_lease(wo, _lease_token(request))
    if agent and entry.get("agent") and agent != entry.get("agent"):
        raise HTTPException(
            status_code=409,
            detail=f"{wo} claimed by {entry.get('agent')}, not {agent}",
        )
    entry["status"] = "in_progress"
    entry["step"] = step
    entry["last_seen"] = _utcnow()
    entry.pop("stuck", None)
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
    _wo_ever_approved.add(wo_id)
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


@app.post("/api/wos/{wo_id}/heartbeat")
async def wo_heartbeat(request: Request, wo_id: str):
    """Lightweight heartbeat — agent signals it is still active without changing step."""
    wo_id = wo_id.upper()
    if not wo_id.startswith("WO-"):
        wo_id = f"WO-{wo_id}"
    entry = _require_lease(wo_id, _lease_token(request))
    entry["last_seen"] = _utcnow()
    entry.pop("stuck", None)
    _save_dispatch()
    return {"ok": True, "wo": wo_id, "last_seen": entry["last_seen"]}


@app.post("/api/validate")
async def request_validation(request: Request, req: ValidateRequest):
    """Agent signals it needs human sign-off before committing.

    Rejects with 422 if CI or security gate not met — the agent must fix
    the failures and call /api/validate again with passing results.
    """
    _enforce_agent_identity(request, req.agent)
    _require_lease(req.wo, _lease_token(request, req.claim_token))
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
        _save_held()
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


@app.post("/api/dispatch/{wo_id}/park")
async def park_dispatch(wo_id: str, request: Request, req: ParkRequest):
    """Park an in-flight WO as awaiting_commit so close-out failures stay visible.

    Does not release the claim. Capacity is freed because awaiting_commit is
    not counted toward MAX_PARALLEL_WOS. Human retries via /retry.
    """
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    status = (req.status or "awaiting_commit").strip().lower()
    if status not in ("awaiting_commit", "awaiting_human"):
        raise HTTPException(
            status_code=400,
            detail="status must be awaiting_commit or awaiting_human",
        )
    entry = _require_lease(wo_id, _lease_token(request, req.claim_token))
    entry["status"] = status
    entry["step"] = req.reason or "parked — needs human"
    entry["parked_at"] = _utcnow()
    entry["last_seen"] = _utcnow()
    _save_dispatch()
    thread_store.append_message(wo_id, thread_store.system_message(
        f"⏸️ Parked as **{status}**" + (f" — {req.reason}" if req.reason else "")
    ))
    print(f"[orchestrator] {wo_id} parked as {status}: {req.reason}")
    return {"ok": True, "wo": wo_id, "status": status}


@app.post("/api/dispatch/{wo_id}/retry")
async def retry_dispatch(wo_id: str, force: bool = False):
    """Reset a failed/stuck WO back to open so the runner picks it up again."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    prev = _dispatch_state.get(wo_id, {})
    # This used to unconditionally overwrite whatever was here — including a
    # WO that already finished and is sitting on a real, good PR waiting for
    # a human. A stale retry request (e.g. queued from Slack before the WO
    # actually completed) would silently discard that state and put a fresh
    # agent to work redoing already-done work. Refuse unless the caller
    # explicitly overrides — mirrors the pattern used elsewhere for
    # destructive resets.
    #
    # Deliberately checks status alone, not pr_url presence: /api/validate
    # only ever sets status to "awaiting_human" on the dispatch entry — the
    # actual PR link lives in the separate _validations queue, not here. A
    # first version of this guard required pr_url too and never fired.
    if prev.get("status") == "awaiting_human" and not force:
        pending = next((v for v in reversed(_validations) if v.get("wo") == wo_id and v.get("status") == "pending"), None)
        pr_hint = f" ({pending['pr_url']})" if pending and pending.get("pr_url") else ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"{wo_id} is awaiting human review{pr_hint} — retry would discard it. "
                f"Merge or close that PR first, or call again with force=true to override."
            ),
        )
    attempt_count = prev.get("attempt_count", 0)
    # Record failed attempt in run history
    try:
        fail_rec = dict(prev)
        fail_rec["wo"] = wo_id
        fail_rec["final_status"] = "failed"
        fail_rec["completed_at"] = _utcnow()
        if not fail_rec.get("failure_reason"):
            fail_rec["failure_reason"] = fail_rec.get("step", "")
        _db_record_run_history(DB_PATH, fail_rec)
    except Exception as exc:
        print(f"[db] error recording history on retry for {wo_id}: {exc}")

    # Preserve attempt_count so the max-retries gate still applies on the next claim.
    # Use a minimal stub rather than deleting so history is kept.
    _dispatch_state[wo_id] = {
        "wo": wo_id,
        "status": "retry_queued",
        "attempt_count": attempt_count,
        "first_claimed_at": prev.get("first_claimed_at", _utcnow()),
        "retried_at": _utcnow(),
    }
    _save_dispatch()
    # A WO can have been auto-held (stuck-timeout watchdog, or 3 cumulative
    # rejections) before landing here. Without this, /api/next's held-check
    # (line ~1313) silently blocks it forever — the status says "retry_queued"
    # but nothing ever actually retries it, and there's no error to notice.
    was_held = wo_id in _held_wos
    _held_wos.discard(wo_id)
    if was_held:
        _save_held()
    # This is the reachable place to detect exhaustion, not the notify block
    # in /api/claim below — /api/next skips any WO at attempt_count >=
    # MAX_RETRY_ATTEMPTS (see the comment there), so nothing ever calls
    # /api/claim for an exhausted WO again and that notify path never fires.
    # Four WOs sat dead for up to a day before anyone noticed, purely because
    # of this gap. This retry call is what the runner makes on every failure
    # (see release_dispatch()), so it's the one place guaranteed to run
    # exactly when a WO's last attempt just failed.
    if attempt_count >= MAX_RETRY_ATTEMPTS and wo_id not in _max_retry_notified:
        _max_retry_notified.add(wo_id)
        thread_store.append_message(wo_id, thread_store.system_message(
            f"🛑 {wo_id} exhausted all {MAX_RETRY_ATTEMPTS} attempts — "
            f"blocked from further claims until manually reset."
        ))
        asyncio.create_task(notify_factory_alert(
            title=f"{wo_id} needs manual reset",
            body=f"Failed all {MAX_RETRY_ATTEMPTS} attempts and will not be retried automatically. "
                 f"POST /api/dispatch/{wo_id}/reset to clear and let the factory retry it.",
            level="urgent",
            source="max-retry-gate",
            secrets=_load_secrets(),
        ))
    print(f"[orchestrator] {wo_id} queued for retry (attempt {attempt_count}, dispatch reset"
          + (", un-held" if was_held else "") + ")")
    return {"ok": True, "retrying": wo_id, "attempt_count": attempt_count, "was_held": was_held}


@app.post("/api/dispatch/{wo_id}/reset")
async def reset_dispatch(wo_id: str, force: bool = False):
    """Force-clear dispatch state including attempt counter — use when max retries exceeded."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    existing = _dispatch_state.get(wo_id, {})
    # Same protection as /retry — this is more destructive (deletes the entry
    # outright), so a WO sitting on a real PR awaiting human review must not
    # be silently wiped by a reset call either.
    if existing.get("status") == "awaiting_human" and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{wo_id} is awaiting human review — reset would discard it. "
                f"Merge or close that PR first, or call again with force=true to override."
            ),
        )
    if wo_id in _dispatch_state:
        try:
            rel_rec = dict(existing)
            rel_rec["wo"] = wo_id
            rel_rec["final_status"] = "released"
            rel_rec["completed_at"] = _utcnow()
            _db_record_run_history(DB_PATH, rel_rec)
        except Exception as exc:
            print(f"[db] error recording history on reset for {wo_id}: {exc}")
        del _dispatch_state[wo_id]
        _save_dispatch()
    dispatch_control.clear_attempt(_attempt_counts, wo_id)
    dispatch_control.save_attempt_counts(ATTEMPTS_PATH, _attempt_counts)
    _max_retry_notified.discard(wo_id)
    _wo_ever_approved.discard(wo_id)
    print(f"[orchestrator] {wo_id} dispatch state hard-reset (attempt counter cleared)")
    return {"ok": True, "reset": wo_id}


@app.delete("/api/dispatch")
async def release_all_dispatch():
    """Clear entire dispatch state — use to reset after a crash or bad run."""
    count = len(_dispatch_state)
    for wo_id, run_data in _dispatch_state.items():
        try:
            rel_rec = dict(run_data)
            rel_rec["wo"] = wo_id
            rel_rec["final_status"] = "released"
            rel_rec["completed_at"] = _utcnow()
            _db_record_run_history(DB_PATH, rel_rec)
        except Exception as exc:
            print(f"[db] error recording history on release_all for {wo_id}: {exc}")
    _dispatch_state.clear()
    _save_dispatch()
    print(f"[orchestrator] dispatch state cleared ({count} entries removed)")
    return {"ok": True, "released": count}


@app.post("/api/complete")
async def complete_wo(request: Request, req: CompleteRequest):
    """Agent signals WO is merged and done."""
    wo_id = req.wo
    _enforce_agent_identity(request, req.agent)
    _require_lease(wo_id, _lease_token(request, req.claim_token))
    _dispatch_state[wo_id]["status"] = "complete"
    _dispatch_state[wo_id]["completed_at"] = _utcnow()
    _wo_ever_approved.discard(wo_id)
    if req.pr_url:
        _dispatch_state[wo_id]["pr_url"] = req.pr_url
    if req.pr_number:
        _dispatch_state[wo_id]["pr_number"] = req.pr_number
    _save_dispatch()
    _db_append_step(wo_id, "complete", step=f"merged by {req.agent}", agent=req.agent)
    
    # Persist to durable run history
    try:
        hist_rec = dict(_dispatch_state[wo_id])
        hist_rec["wo"] = wo_id
        hist_rec["final_status"] = "complete"
        hist_rec["agent"] = req.agent or hist_rec.get("agent", "")
        hist_rec["step"] = f"merged by {req.agent}"
        if req.pr_url:
            hist_rec["pr_url"] = req.pr_url
        if req.pr_number:
            hist_rec["pr_number"] = req.pr_number
        _db_record_run_history(DB_PATH, hist_rec)
    except Exception as exc:
        print(f"[db] error recording history for {wo_id}: {exc}")

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

    target_repo = (_dispatch_state.get(wo_id) or {}).get("repo")
    if not target_repo and _specs_cache:
        n_val = int(wo_num) if wo_num.isdigit() else None
        if n_val is not None:
            target_repo = (_specs_cache.get(n_val) or {}).get("repo")
    target_repo = target_repo or GITHUB_REPO

    target_wo_path = WO_PATH
    for p in _get_configured_repos():
        if p.get("repo") == target_repo:
            target_wo_path = p.get("wo_path") or WO_PATH
            break

    async with httpx.AsyncClient(timeout=20) as client:
        # ── 1. Update spec file ──────────────────────────────────────────────
        try:
            files = await _cached_get(client, f"/repos/{target_repo}/contents/{target_wo_path}",
                                       {}, ttl=60)
            spec_file = next(
                (f for f in files if re.match(rf"WO-{wo_num}-", f["name"])),
                None,
            )
            if spec_file:
                file_data = await _get(client, f"/repos/{target_repo}/contents/{spec_file['path']}")
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
                        f"https://api.github.com/repos/{target_repo}/contents/{spec_file['path']}",
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
                existing = await _get(client, f"/repos/{target_repo}/contents/{claim_path}")
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
                f"https://api.github.com/repos/{target_repo}/contents/{claim_path}",
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
        try:
            rec = dict(_dispatch_state[wo_id])
            rec["wo"] = wo_id
            rec["final_status"] = "complete"
            rec["step"] = "auto-marked done by pr-watchdog"
            if pr_url:
                rec["pr_url"] = pr_url
            if pr_number:
                rec["pr_number"] = pr_number
            if merged_at:
                rec["completed_at"] = merged_at
            _db_record_run_history(DB_PATH, rec)
        except Exception as exc:
            print(f"[db] error recording history on auto-mark-done for {wo_id}: {exc}")
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

def _thread_wo(wo: str) -> str:
    try:
        return thread_store.require_wo_id(wo)
    except thread_store.UnsafePath:
        raise HTTPException(status_code=400, detail="invalid wo id")


def _thread_image_filename(name: str) -> str:
    try:
        return thread_store.require_image_filename(name)
    except thread_store.UnsafePath:
        raise HTTPException(status_code=400, detail="invalid filename")


@app.post("/api/thread/{wo}/messages")
async def post_thread_message(wo: str, msg: ThreadMessage):
    """Post a message to a WO's thread (agent or human)."""
    wo = _thread_wo(wo)
    image_url = msg.image_url

    if msg.image_data:
        images_root = DATA_DIR / "threads" / "images"
        try:
            images_dir = thread_store.contained_path(images_root, wo)
        except thread_store.UnsafePath:
            raise HTTPException(status_code=400, detail="invalid wo id")
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
    wo = _thread_wo(wo)
    filename = _thread_image_filename(filename)
    try:
        path = thread_store.contained_path(DATA_DIR / "threads" / "images", wo, filename)
    except thread_store.UnsafePath:
        raise HTTPException(status_code=400, detail="invalid path")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/thread/{wo}/messages")
async def get_thread_messages(wo: str, since: str = ""):
    """Return all messages for a WO, or only those after `since` (message id)."""
    wo = _thread_wo(wo)
    messages = thread_store.load_thread(wo)
    if since:
        messages = [m for m in messages if m.get("id", "") > since]
    return messages


@app.get("/api/thread/{wo}/stream")
async def stream_thread(wo: str, since: str = ""):
    """SSE stream — sends new thread messages as they arrive (2 s poll)."""
    wo = _thread_wo(wo)
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
    """Full dispatch state — which agent owns which WO. Claim tokens are never returned."""
    return {wo_id: _public_dispatch_entry(entry) for wo_id, entry in _dispatch_state.items()}


@app.get("/api/runs/{wo_id}/history")
async def get_run_history(wo_id: str):
    """Step audit log for a single WO — who did what and when."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    try:
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
        with _db() as conn:
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
    token = _get_github_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None):
    url = f"https://api.github.com{path}"
    resp = await client.get(url, headers=_headers(), params=params or {})
    resp.raise_for_status()
    return resp.json()


async def _get_repo_variable(client: httpx.AsyncClient, repo: str, name: str) -> str | None:
    """Read a GitHub Actions repo variable. None if unset or the repo/token can't be reached."""
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/actions/variables/{name}", headers=_headers()
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("value")
    except Exception as e:
        print(f"[orchestrator] _get_repo_variable {repo}/{name} failed: {e}")
        return None


async def _set_repo_variable(client: httpx.AsyncClient, repo: str, name: str, value: str) -> None:
    """Create or update a GitHub Actions repo variable (PATCH if it exists, else POST)."""
    resp = await client.patch(
        f"https://api.github.com/repos/{repo}/actions/variables/{name}",
        headers=_headers(),
        json={"name": name, "value": value},
    )
    if resp.status_code == 404:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/actions/variables",
            headers=_headers(),
            json={"name": name, "value": value},
        )
    resp.raise_for_status()


async def _delete_repo_variable(client: httpx.AsyncClient, repo: str, name: str) -> None:
    """Remove a GitHub Actions repo variable. No-op (not an error) if it never existed."""
    resp = await client.delete(
        f"https://api.github.com/repos/{repo}/actions/variables/{name}", headers=_headers()
    )
    if resp.status_code not in (204, 404):
        resp.raise_for_status()


# ── WO spec parsing ───────────────────────────────────────────────────────────

def _parse_wo_number(filename: str) -> int | None:
    m = re.match(r"WO-(\d+)", filename)
    return int(m.group(1)) if m else None


def _parse_status(content: str) -> str:
    m = re.search(r"\*\*Status:\*\*\s*(.+)", content)
    return m.group(1).strip() if m else "Open"


_PRIORITY_LEVEL_RE = re.compile(r"\bP([0-3])\b")

def _parse_priority(content: str) -> str:
    m = re.search(r"\*\*Priority:\*\*\s*(.+)", content)
    if not m:
        return "P2"
    raw = m.group(1).strip()
    pm = _PRIORITY_LEVEL_RE.search(raw)
    return f"P{pm.group(1)}" if pm else "P2"


def _parse_title(content: str, number: int) -> str:
    m = re.search(r"^# (?:WO-[\d–-]+|Work Order \d+)\s*[—:]\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else f"WO-{number}"


def _parse_effort(content: str) -> str:
    m = re.search(r"\*\*(?:Estimated )?[Ee]ffort:\*\*\s*(.+)", content)
    if not m:
        return ""
    raw = m.group(1).strip()
    # Normalize to canonical size token (XS/S/M/L/XL)
    size = re.match(r"(XS|S|M|L|XL)\b", raw, re.IGNORECASE)
    return size.group(1).upper() if size else raw


def _infer_phase(priority: str) -> str:
    """Default phase for a spec-file WO with no PLAN.json entry."""
    return "now" if priority in ("P0", "P1") else "backlog"


def _parse_depends_on(content: str) -> list[int]:
    # Stop at the first ';' — the convention for soft/non-blocking notes is
    # "**Depends on:** WO-A, WO-B; WO-C should ideally land first ... but is
    # not blocking" on one line. Capturing the whole line (previous behavior)
    # pulled WO-C in as a hard dependency despite the spec explicitly saying
    # it isn't one.
    m = re.search(r"\*\*Depends on:\*\*\s*([^;\n]+)", content)
    if not m:
        return []
    return [int(n) for n in re.findall(r"WO-(\d+)", m.group(1))]


def _parse_files_likely_changed(content: str) -> list[str]:
    """Extract the file paths from a WO's '## Files Likely Changed' section.

    Used to warn the dispatcher off handing out a WO whose declared scope
    overlaps with one already being actively worked by another agent — WOs
    with no declared relationship to each other (no depends_on) can still
    genuinely collide on the same file. Backtick-quoted, dot-extension
    tokens only, so inline symbol/variable names mentioned in parens
    (e.g. "`ROLE_GROUPS` lives with the other metadata") aren't mistaken
    for file paths."""
    m = re.search(r"## Files Likely Changed\s*\n(.*?)(?:\n## |\Z)", content, re.DOTALL)
    if not m:
        return []
    return re.findall(r"`([^`]+\.[a-zA-Z]+)`", m.group(1))


def _is_done(status: str) -> bool:
    # Match on status PREFIX only — substring matching causes "conflict advisor v1 done"
    # or "deferred to WO-226" to incorrectly mark a WO as done/deferred.
    # classify_wo_status strips leading emoji so "⛔ Superseded" / "❌ Cancelled"
    # are terminal rather than lingering in Open.
    return classify_wo_status(status) in ("done", "deferred")


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
    return classify_wo_status(status) == "blocked"


def _trust_dispatch_complete(num: int, entry: dict, specs: dict[int, dict]) -> bool:
    """Whether a dispatch 'complete' row may hide a WO from Open.

    A real agent completion (F-01) wins over a spec that has not been
    rewritten yet. A back-fill stub (agent unknown/empty) from a filing PR
    must not hide work whose spec is still Planned/Open.
    """
    spec = specs.get(num)
    if spec is None:
        return True
    if _is_done(spec.get("status", "")):
        return True
    agent = (entry.get("agent") or "").strip().lower()
    return bool(agent) and agent != "unknown"


def _claim_blocks_next(wo_id: str, claim: dict, specs: dict[int, dict]) -> bool:
    """Whether /api/next should skip this WO because of dispatch_state.

    Untrusted complete stubs (agent empty/unknown, spec still open) must not
    hide work — same rule as _trust_dispatch_complete / F-01. pending_approval
    and preflight_held are unclaimable until a human or preflight clears them,
    so skip them or every runner poll sticks on the same 423.
    """
    status = claim.get("status")
    if status in ("claimed", "in_progress", "awaiting_human", "awaiting_commit",
                  "pending_approval", "preflight_held"):
        return True
    if status != "complete":
        return False
    try:
        num = int(str(wo_id).replace("WO-", ""))
    except ValueError:
        return True
    return _trust_dispatch_complete(num, claim, specs)


def _occupancy_reason_for(wo_id: str) -> str | None:
    """External occupancy: Clarion claim file, open PR, or dirty/wrong-branch worktree."""
    num = occupancy.wo_num_from_id(wo_id)
    if num is None:
        return None
    factory_status = (_dispatch_state.get(wo_id) or {}).get("status", "")
    claim = None
    worktrees = None
    if LOCAL_REPO_MOUNT:
        claim = occupancy.load_claim_file(LOCAL_REPO_MOUNT, num, RUNS_PATH)
        worktrees = occupancy.inspect_worktrees(LOCAL_REPO_MOUNT, num)
    return occupancy.occupancy_reason(
        wo_num=num,
        claim=claim,
        worktrees=worktrees,
        open_pr_urls=_open_pr_urls,
        factory_status=factory_status,
    )


def _dependency_satisfied(dep_num: int, specs: dict[int, dict],
                          dispatch_state: dict) -> bool:
    """True when a depends_on target is actually done (spec or trusted complete)."""
    spec = specs.get(dep_num) or {}
    if spec and _is_done(spec.get("status", "")):
        return True
    entry = dispatch_state.get(f"WO-{dep_num}", {})
    return entry.get("status") == "complete" and _trust_dispatch_complete(
        dep_num, entry, specs
    )


# ── GitHub data fetchers ──────────────────────────────────────────────────────

def _read_local_wo_specs(repo_root: str, wo_path: str, repo: str) -> dict[int, dict]:
    """Read WO spec files from origin/main (fetch-only) with filesystem fallback.

    Never depends on the operator's working-tree checkout being on main.
    """
    specs: dict[int, dict] = {}

    def _spec_from_content(num: int, content: str) -> dict:
        return {
            "number": num,
            "repo": repo,
            "title": _parse_title(content, num),
            "status": _parse_status(content),
            "priority": _parse_priority(content),
            "effort": _parse_effort(content),
            "depends_on": _parse_depends_on(content),
            "files_likely_changed": _parse_files_likely_changed(content),
            "services": sorted(conflict_advisor.parse_services_from_spec(content)),
            "_raw_body": content,
        }

    files = occupancy.read_tree_files(repo_root, "origin/main", wo_path)
    for fname, content in files.items():
        num = _parse_wo_number(fname)
        if not num:
            continue
        specs[num] = _spec_from_content(num, content)
    if specs:
        return specs

    wo_dir = Path(repo_root) / wo_path
    if not wo_dir.is_dir():
        return specs
    for f in wo_dir.glob("WO-*.md"):
        num = _parse_wo_number(f.name)
        if not num:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            specs[num] = _spec_from_content(num, content)
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
                "files_likely_changed": _parse_files_likely_changed(content),
                "services": sorted(conflict_advisor.parse_services_from_spec(content)),
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
                # git lists remote branches as "  origin/wo/NNN-slug"
                ref = line.strip().removeprefix("origin/")
                n = extract_wo_from_branch(ref)
                if n is not None:
                    results.add(n)
            return results
        except Exception as e:
            print(f"[orchestrator] Local branch read failed: {e}")

    try:
        branches = await _get(client, f"/repos/{repo}/branches", {"per_page": 100})
        return {n for b in branches if (n := extract_wo_from_branch(b["name"])) is not None}
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
    global _open_pr_wos, _open_pr_urls
    try:
        prs = await _cached_get(client, f"/repos/{repo}/pulls", {"state": "open", "per_page": 100})
        # resolve_all_wos_for_pr, not resolve_wo_for_pr: this set feeds the
        # open_wos/pr_wos skip-check in /api/next — a PR whose title names two
        # WOs (conflict-resolution / follow-up PRs) must keep BOTH out of the
        # dispatch queue, not just whichever one the single-result resolver
        # matches first. Missing this let the second WO get redispatched to a
        # fresh agent while its real PR was already open, awaiting review.
        wos: set[int] = set()
        urls: dict[int, str] = {}
        for p in prs:
            url = p.get("html_url") or ""
            for n in resolve_all_wos_for_pr(p):
                wos.add(n)
                if url and n not in urls:
                    urls[n] = url
        _open_pr_wos = wos
        _open_pr_urls = urls
        return wos
    except Exception:
        return set(_open_pr_wos)


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
    """Return {wo_number: pr_html_url} for WO PRs merged in the last 90 days.

    Uses wos_completed_by_merged_pr so a docs filing PR on a wo/NNN- branch
    (e.g. 'docs(wo): file WO-482') does not auto-complete the WO, and a
    'WO-NNN:' title still counts when the branch is docs/.
    """
    since = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        prs = await _cached_get(client, f"/repos/{GITHUB_REPO}/pulls",
                                 {"state": "closed", "per_page": 100, "sort": "updated", "direction": "desc"},
                                 ttl=300)
        result: dict[int, str] = {}
        for p in prs:
            if p.get("merged_at") and p["merged_at"] >= since:
                for n in wos_completed_by_merged_pr(p):
                    result.setdefault(n, p.get("html_url", ""))
        return result
    except Exception:
        return {}


async def _fetch_plan(client: httpx.AsyncClient) -> dict | None:
    # Prefer origin/main so we don't depend on the operator's working tree.
    if LOCAL_REPO_MOUNT:
        raw = occupancy.git_show(LOCAL_REPO_MOUNT, f"origin/main:{PLAN_PATH}")
        if raw:
            try:
                return json.loads(raw)
            except Exception as e:
                print(f"[orchestrator] Failed to parse origin/main PLAN.json: {e}")
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
            if entry.get("status") in ("claimed", "rejected", "pending_approval", "preflight_held"):
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
    """Fetch origin/main and origin/wo/* so spec reads via `git show` stay fresh.

    Never merges into LOCAL_REPO_MOUNT — that is the operator's working clone.
    A ff-only merge of origin/main onto a dirty or feature-branch checkout
    overwrites in-progress human work.
    """
    if not LOCAL_REPO_MOUNT:
        return
    token = _get_github_token()
    if not token or not GITHUB_REPO:
        return
    https_url = github_https_url(GITHUB_REPO)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "fetch", "--prune", https_url,
            "main:refs/remotes/origin/main",
            "+refs/heads/wo/*:refs/remotes/origin/wo/*",
            cwd=LOCAL_REPO_MOUNT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=git_fetch_env(token),
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            msg = redact_secret(err.decode(errors="replace"), token).strip()[:200]
            print(f"[orchestrator] git fetch failed: {msg}")
            return
        print("[orchestrator] local repo fetch ok (working tree untouched)")
    except Exception as e:
        print(f"[orchestrator] git fetch error: {redact_secret(str(e), token)}")


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
    #
    # A claim can look dead purely on timing even when the agent actually
    # finished — the review chain + CI + commit/push/PR sequence has real
    # gaps between heartbeats, and a slow-but-successful run can outlast
    # CLAIM_TIMEOUT_SECONDS. Before discarding a "stale" claim, check whether
    # a PR already exists for it on GitHub; if so, the agent didn't die, it
    # finished and just never got to report back. Recover it into the human
    # validation queue instead of silently losing completed work and burning
    # a retry attempt on a WO that isn't actually broken.
    stale_candidates = []
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
            stale_candidates.append((wo_id, entry, int(age / 60)))

    pr_by_wo: dict[int, dict] = {}
    if stale_candidates:
        try:
            async with httpx.AsyncClient(timeout=15) as _pc:
                open_prs = await _cached_get(_pc, f"/repos/{GITHUB_REPO}/pulls", {"state": "open", "per_page": 100})
            for p in open_prs:
                # resolve_all_wos_for_pr, not resolve_wo_for_pr: a conflict-resolution
                # or follow-up PR can genuinely close two WOs in one title (e.g.
                # "WO-1035: Resolve conflict — WO-417: ..."). The single-result
                # resolver only credits whichever number its regex matches first,
                # so a stale claim on the *other* WO named in that same PR would
                # never find it here and get wrongly discarded instead of recovered.
                for n in resolve_all_wos_for_pr(p):
                    pr_by_wo[n] = p
        except Exception as e:
            print(f"[orchestrator] stale-sweep PR lookup failed: {e}")

    stale_released = []
    recovered = []
    for wo_id, entry, age_min in stale_candidates:
        try:
            live = dispatch_control.live_claim(_dispatch_state, wo_id)
            if live is None:
                continue
            agent_name = live.get("agent", "unknown")
            try:
                wo_num = int(wo_id.replace("WO-", ""))
            except ValueError:
                wo_num = None
            pr = pr_by_wo.get(wo_num) if wo_num is not None else None

            if pr:
                pr_url = pr.get("html_url", "")
                print(f"[orchestrator] {wo_id} claim looked stale ({age_min}m) but PR #{pr.get('number')} already exists — recovering instead of discarding")
                live["status"] = "awaiting_human"
                live["pr_url"] = pr_url
                live["pr_number"] = pr.get("number")
                recovered.append((wo_id, agent_name, age_min, pr_url))
                thread_store.append_message(wo_id, thread_store.system_message(
                    f"⚠️ Claim went quiet for {age_min} minutes, but PR already exists — "
                    f"the agent finished, it just didn't check back in. Recovered to awaiting human review: {pr_url}"
                ))
                continue

            print(f"[orchestrator] {wo_id} stale claim ({age_min}m, agent={agent_name}) — releasing")
            live["status"] = "stale"
            live["stale_at"] = _utcnow()
            stale_released.append((wo_id, agent_name, age_min))
            thread_store.append_message(wo_id, thread_store.system_message(
                f"⚠️ Claim expired after {age_min} minutes — agent `{agent_name}` appears dead. Re-queuing."
            ))
            # This sweep doesn't touch attempt_count — it's only ever incremented
            # in /api/claim — but if the claim that just went stale was already
            # the last allowed attempt, /api/next will now permanently skip this
            # WO (see the comment there) and nothing will ever call /api/claim or
            # /api/dispatch/{wo}/retry for it again. Same exhaustion gap as
            # /retry, different trigger (timeout instead of an explicit failure).
            stale_attempt_count = live.get("attempt_count", 0)
            if stale_attempt_count >= MAX_RETRY_ATTEMPTS and wo_id not in _max_retry_notified:
                _max_retry_notified.add(wo_id)
                thread_store.append_message(wo_id, thread_store.system_message(
                    f"🛑 {wo_id} exhausted all {MAX_RETRY_ATTEMPTS} attempts (last one timed out) — "
                    f"blocked from further claims until manually reset."
                ))
                asyncio.create_task(notify_factory_alert(
                    title=f"{wo_id} needs manual reset",
                    body=f"Its last attempt timed out (agent went quiet) and it has now failed all "
                         f"{MAX_RETRY_ATTEMPTS} attempts. POST /api/dispatch/{wo_id}/reset to clear and retry.",
                    level="urgent",
                    source="max-retry-gate",
                    secrets=_load_secrets(),
                ))
        except Exception as e:
            print(f"[orchestrator] stale-sweep {wo_id} failed: {e}")
    if recovered:
        _save_dispatch()
        for wo_id, agent_name, age_min, pr_url in recovered:
            asyncio.create_task(notify_factory_alert(
                title=f"{wo_id} recovered — PR ready for review",
                body=f"Agent `{agent_name}` went quiet for {age_min}m but had already opened {pr_url}. No work lost.",
                level="info",
                source="stale-claim-sweep",
                secrets=_load_secrets(),
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

    # Preflight retry sweep: re-check WOs held for unmet environment requirements.
    for wo_id, pf in list(_preflight_held.items()):
        try:
            last_checked = pf.get("last_checked", pf.get("held_at", ""))
            try:
                age = (datetime.now(UTC) - datetime.fromisoformat(last_checked.replace("Z", "+00:00"))).total_seconds()
            except Exception:
                continue
            if age < PREFLIGHT_RETRY_SECONDS:
                continue  # not time to re-check yet
            requires = pf.get("requires", {})
            if not requires:
                # No requires data — can't re-check, remove from held and let it dispatch
                _preflight_held.pop(wo_id, None)
                _dispatch_state.pop(wo_id, None)
                continue
            new_failures = await preflight_check(requires)
            pf = _preflight_held.get(wo_id)
            if pf is None:
                continue
            pf["last_checked"] = _utcnow()
            if not new_failures:
                # Requirements now met — release from hold
                print(f"[orchestrator] {wo_id} preflight requirements met — re-queuing")
                _preflight_held.pop(wo_id, None)
                _dispatch_state.pop(wo_id, None)
                _save_dispatch()
                thread_store.append_message(wo_id, thread_store.system_message(
                    f"✅ {wo_id} environment requirements now met — re-queuing for dispatch"
                ))
                asyncio.create_task(notify_factory_alert(
                    title=f"{wo_id} re-queued — environment ready",
                    body=f"{wo_id} held WO automatically re-queued: all preflight requirements now met.",
                    level="info",
                    source="preflight-retry",
                    secrets=_load_secrets(),
                ))
            else:
                pf["hold_reason"] = new_failures
                if wo_id in _dispatch_state:
                    _dispatch_state[wo_id]["hold_reason"] = new_failures
                    _dispatch_state[wo_id]["last_checked"] = _utcnow()
                print(f"[orchestrator] {wo_id} preflight still failing: {'; '.join(new_failures)}")
        except Exception as e:
            print(f"[orchestrator] preflight-retry {wo_id} failed: {e}")

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
    # Spec files that already say Done/Deferred/Superseded must close a
    # leftover in_progress claim — otherwise dashboard apply_live_status
    # treats dispatch as live and refuses to honor the merged PR.
    for num, spec in primary_specs.items():
        if not _is_done(spec.get("status", "")):
            continue
        wo_id = f"WO-{num}"
        entry = _dispatch_state.get(wo_id)
        if entry is None or entry.get("status") in ("complete", "rejected"):
            continue
        entry["status"] = "complete"
        entry["completed_at"] = _utcnow()
        entry["step"] = entry.get("step") or "spec marked done"
        _dispatch_state[wo_id] = entry
        _db_append_step(wo_id, "complete", step="spec marked done (auto-reconcile)")
        reconciled += 1
    if reconciled:
        _save_dispatch()
        print(f"[orchestrator] poll: auto-completed {reconciled} WO(s) from merged PRs")

    # Combine specs, active branches, and open PRs across all configured projects
    specs: dict[int, dict] = {}
    active_branch_wos: set[int] = set()
    pr_wos: set[int] = set()

    for idx, p in enumerate(configured_projects):
        p_repo = p["repo"]
        p_path = p.get("wo_path") or WO_PATH
        for num, spec in specs_results[idx].items():
            if num not in specs or p.get("primary"):
                s_copy = dict(spec)
                s_copy["repo"] = p_repo
                s_copy["wo_path"] = p_path
                specs[num] = s_copy
        active_branch_wos.update(branch_results[idx])
        pr_wos.update(pr_results[idx])

    global _specs_cache
    _specs_cache = dict(specs)  # snapshot for PM chat context injection

    # Sets for board summary use all specs
    dispatch_done = {
        int(k[3:]) for k, v in _dispatch_state.items()
        if k.startswith("WO-") and k[3:].isdigit() and v.get("status") == "complete"
        and _trust_dispatch_complete(int(k[3:]), v, specs)
    }
    done_wos = {num for num, s in specs.items() if _is_done(s["status"])} | dispatch_done
    in_progress_wos = active_branch_wos - pr_wos - done_wos
    in_review_wos = pr_wos - done_wos
    open_wos = {num for num, s in specs.items()
                if not _is_done(s["status"]) and num not in dispatch_done
                and num not in active_branch_wos and num not in pr_wos}
    blocked_wos = {num for num, s in specs.items() if _is_blocked(s["status"])}

    # Build plan dict from DB (queue / phases / milestones)
    plan_dict = _db_build_plan_dict()
    wo_statuses = _build_wo_statuses(primary_specs, active_branch_wos, pr_wos,
                                     {n for n in done_wos if n in primary_specs})
    plan_next = next_wo(plan_dict, wo_statuses) if plan_dict.get("queue") else None
    plan_queue_sorted = sorted_queue(plan_dict, wo_statuses)

    dispatch_queue, holding_queue, cycle_warnings = _resolve_dependencies(
        {num: s for num, s in specs.items() if num in open_wos}, done_wos,
        dispatch_state=_dispatch_state,
    )

    # Build runtime overlay — spec-file WOs not registered in the DB queue.
    # "conflict advisor v1 done" does NOT cause a WO to be excluded from the overlay.
    global _plan_overlay
    plan_registered = _db_get_queue_wo_ids()
    _plan_overlay = []
    for num, spec in sorted(specs.items()):
        wo_id = f"WO-{num}"
        # Audit F-01: same dispatch_done precedence as open_wos above — this
        # overlay directly feeds /api/next's dispatch queue, so a WO the
        # orchestrator already knows is complete must not be re-offered just
        # because the spec file's status text hasn't been rewritten yet.
        if _is_done(spec.get("status", "")) or num in dispatch_done or _is_blocked(spec.get("status", "")):
            continue
        entry = {
            "wo": wo_id,
            "title": spec.get("title", wo_id),
            "priority": spec.get("priority", "P2"),
            "effort": spec.get("effort", ""),
            "status": spec.get("status", "open"),
            "depends_on": spec.get("depends_on", []),
            "files_likely_changed": spec.get("files_likely_changed", []),
            "services": spec.get("services", []),
            "repo": spec.get("repo", GITHUB_REPO),
            "wo_path": spec.get("wo_path", WO_PATH),
            "_overlay": True,
        }
        if wo_id in plan_registered:
            # Already registered — only refresh spec-derived fields (priority/
            # title/effort/depends_on/files_likely_changed). Never overwrite
            # human-set phase/pin/position for existing rows. depends_on and
            # files_likely_changed aren't something humans hand-edit via the
            # board the way phase/pin/position are, so they must stay in sync
            # — previously frozen at whatever they were on first registration,
            # silently going stale if a WO's spec changed later.
            with _db() as _conn:
                _conn.execute(
                    "UPDATE queue SET priority=?, title=?, effort=?, depends_on=?, files_likely_changed=? WHERE wo=?",
                    (entry["priority"], entry["title"], entry["effort"],
                     json.dumps(entry["depends_on"]), json.dumps(entry["files_likely_changed"]), wo_id),
                )
            continue
        _plan_overlay.append(entry)
        # Persist to SQLite so the queue stays current without manual PLAN.json edits.
        # ON CONFLICT DO UPDATE preserves any human-set position/pin/phase already in the DB.
        # Phase is inferred from priority (P0/P1→now, P2/P3→backlog) when not in PLAN.json.
        _db_upsert_queue_entry({**entry, "phase": spec.get("phase") or _infer_phase(entry["priority"])})

    # Write back any newly-discovered WOs to PLAN.json so humans can see them without
    # querying the DB. Only appends — never overwrites human-set fields.
    if _plan_overlay and LOCAL_REPO_MOUNT:
        _writeback_plan_json([e for e in _plan_overlay])

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

    # Stuck detection: flag claimed WOs with no activity beyond their priority threshold
    now_dt = datetime.now(UTC)
    state_changed = False
    for wo_id, entry in _dispatch_state.items():
        if entry.get("status") not in ("claimed", "in_progress"):
            continue
        last_seen_str = entry.get("last_seen") or entry.get("claimed_at")
        if not last_seen_str:
            continue
        try:
            last_seen_dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        try:
            wo_num = int(wo_id.replace("WO-", ""))
        except ValueError:
            continue
        spec = primary_specs.get(wo_num, {})
        priority = spec.get("priority", "P2")
        threshold = STUCK_THRESHOLDS.get(priority, timedelta(hours=24))
        idle = now_dt - last_seen_dt
        was_stuck = entry.get("stuck", False)
        if idle > threshold:
            if not was_stuck:
                entry["stuck"] = True
                entry["stuck_since"] = last_seen_str
                _dispatch_state[wo_id] = entry
                state_changed = True
                print(f"[orchestrator] ⚠️  {wo_id} STUCK — no activity for {idle} (threshold: {threshold}, priority: {priority})")
            if idle > threshold * 2:
                wo_id_str = wo_id
                if wo_id_str not in _held_wos:
                    _held_wos.add(wo_id_str)
                    _save_held()
                    state_changed = True
                    print(f"[orchestrator] ⛔ {wo_id} auto-held after {idle} — human must review and un-hold")
                    asyncio.create_task(notify_factory_alert(
                        title=f"{wo_id} auto-held — stuck with no activity",
                        body=f"No activity for {idle} (priority threshold: {threshold}). Un-hold once reviewed.",
                        level="warning",
                        source="stuck-detector",
                        secrets=_load_secrets(),
                    ))
        else:
            if was_stuck:
                entry.pop("stuck", None)
                entry.pop("stuck_since", None)
                _dispatch_state[wo_id] = entry
                state_changed = True
    if state_changed:
        _save_dispatch()

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
    dispatch_control.atomic_write_json(OUTPUT_PATH, _orchestrator_output)
    print(f"[orchestrator] {now_str} — {len(specs)} WOs, {len(dispatch_queue)} dispatchable, "
          f"{len(in_progress_wos)} in-progress, {len(pending_validations)} awaiting validation")

    # Stall detection — mirrors /api/next's own "not done, not held" filter over
    # plan.queue so this fires exactly when a runner polling /api/next would keep
    # getting "queue empty or all candidates claimed/blocked" back.
    global _stall_since, _stall_alerted
    active_now = sum(1 for c in _dispatch_state.values() if c.get("status") in ("claimed", "in_progress"))
    queue_candidates = [w for w in _orchestrator_output["plan"]["queue"] if not _is_done(w.get("status", ""))]
    unheld_candidates = [w for w in queue_candidates if w.get("wo") not in _held_wos]
    stalled_now = active_now == 0 and bool(queue_candidates) and not unheld_candidates
    if stalled_now:
        if _stall_since is None:
            _stall_since = now_str
            _stall_alerted = False
        else:
            elapsed = (datetime.now(UTC) - datetime.fromisoformat(_stall_since.replace("Z", "+00:00"))).total_seconds()
            if elapsed > STALL_ALERT_THRESHOLD_SECONDS and not _stall_alerted:
                held_ids = ", ".join(str(w.get("wo")) for w in queue_candidates[:10])
                asyncio.create_task(notify_factory_alert(
                    title="Factory idle — entire dispatch queue is held",
                    body=(
                        f"{len(queue_candidates)} WO(s) queued, none active, and every one is on "
                        f"hold — idle for over {int(STALL_ALERT_THRESHOLD_SECONDS // 3600)}h. "
                        f"Held: {held_ids}"
                    ),
                    level="warning",
                    source="stall-detector",
                    secrets=_load_secrets(),
                ))
                _stall_alerted = True
    else:
        _stall_since = None
        _stall_alerted = False

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
    # automation_model is a convenience read here for callers (e.g. agent-runner)
    # that already poll this endpoint for live config. It's not persisted in
    # agent_config.json — /api/settings/automation-model is the write path,
    # backed by a GitHub repo variable rather than the local config file since
    # GitHub-Actions-run scripts need to read it too.
    return {**_load_agent_config(), "automation_model": _get_model()}


@app.put("/api/config")
async def put_agent_config(request: Request):
    try:
        incoming = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        merged = apply_agent_config_updates(_load_agent_config(), incoming)
    except AgentConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    dispatch_control.atomic_write_json(AGENT_CONFIG_PATH, merged)
    return merged


# ── Usage tracking endpoints ──────────────────────────────────────────────────

USAGE_PATH = DATA_DIR / "usage.json"
ANTHROPIC_USAGE_PATH = DATA_DIR / "anthropic_usage.json"

# Approximate cost per million tokens (USD) — update if Anthropic changes pricing.
# Falls back to the sonnet-tier rate below for any model not listed here (e.g. a
# model chosen via the Automation Model setting that predates this table) —
# an estimate, not a crash, since the model is now user-changeable.
_ANTHROPIC_PRICING: dict[str, dict] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-sonnet-5":           {"input": 3.00, "output": 15.00},
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
        dispatch_control.atomic_write_json(ANTHROPIC_USAGE_PATH, records)
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
    dispatch_control.atomic_write_json(USAGE_PATH, records)
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


# ── Secrets (Vault KV v2 + file fallback) ────────────────────────────────────

VAULT_ADDR = os.getenv("VAULT_ADDR", "")
_VAULT_KEYS_DIR = Path("/vault/keys")
_VAULT_SECRETS_PATH = "v1/secret/data/factory/secrets"
SECRETS_PATH = DATA_DIR / "secrets.json"
_secrets_cache: dict = {}
_vault_token: str = ""  # set in _init_secrets() at startup


def _load_secrets() -> dict:
    """Return in-memory secrets cache (populated from Vault or file on startup)."""
    return dict(_secrets_cache)


def _load_secrets_file() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    try:
        return json.loads(SECRETS_PATH.read_text())
    except Exception:
        return {}


async def _vault_read() -> dict:
    if not VAULT_ADDR or not _vault_token:
        return {}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"{VAULT_ADDR}/{_VAULT_SECRETS_PATH}",
                headers={"X-Vault-Token": _vault_token},
            )
            if r.status_code == 200:
                return r.json().get("data", {}).get("data", {}) or {}
            if r.status_code == 404:
                return {}
            print(f"[secrets] Vault read HTTP {r.status_code}")
    except Exception as e:
        print(f"[secrets] Vault read error: {e}")
    return {}


async def _vault_write(secrets: dict) -> None:
    if not VAULT_ADDR or not _vault_token:
        return
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.put(
            f"{VAULT_ADDR}/{_VAULT_SECRETS_PATH}",
            headers={"X-Vault-Token": _vault_token, "Content-Type": "application/json"},
            json={"data": secrets},
        )
        if r.status_code not in (200, 204):
            raise RuntimeError(f"Vault write HTTP {r.status_code}: {r.text[:200]}")


async def _init_secrets() -> None:
    """Load secrets from Vault (or file fallback) into the in-memory cache."""
    global _secrets_cache, _vault_token
    _vault_token = load_vault_token(_VAULT_KEYS_DIR)
    if VAULT_ADDR and _vault_token:
        vault_data = await _vault_read()
        if not vault_data:
            file_data = _load_secrets_file()
            if file_data:
                print(f"[secrets] Migrating {len(file_data)} secrets from file to Vault…")
                try:
                    await _vault_write(file_data)
                    vault_data = file_data
                    SECRETS_PATH.rename(SECRETS_PATH.with_suffix(".json.migrated"))
                except Exception as e:
                    print(f"[secrets] Vault migration failed: {e} — using file fallback")
                    vault_data = file_data
        _secrets_cache = vault_data
        print(f"[secrets] {len(_secrets_cache)} secret(s) loaded from Vault")
    else:
        _secrets_cache = _load_secrets_file()
        print(f"[secrets] Vault not configured — {len(_secrets_cache)} secret(s) from file")


@app.get("/api/secrets")
async def get_secrets():
    """Return which secret keys are set — never their values."""
    return {k: bool(v) for k, v in _load_secrets().items()}


@app.put("/api/secrets")
async def put_secrets(request: Request):
    global _secrets_cache
    try:
        incoming = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        secrets = apply_secret_updates(_secrets_cache, incoming)
    except SecretPolicyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if VAULT_ADDR and _vault_token:
        await _vault_write(secrets)
    else:
        dispatch_control.atomic_write_json(SECRETS_PATH, secrets)
    _secrets_cache = secrets
    return {k: bool(v) for k, v in secrets.items()}


# ── WO Draft generation ────────────────────────────────────────────────────────

# Each backend now runs as its own native launchd process (claude/cursor/codex on
# ports 8102/8103/8104 — see scripts/agent-install.sh), not one generic runner on
# 8101. Any single draft-server instance can answer for the whole fleet (it manages
# LaunchAgents by label, and probes all backend CLIs, not just its own), so this
# just needs to resolve to whichever port is actually alive right now.
_AGENT_RUNNER_ENV_OVERRIDE = os.getenv("AGENT_RUNNER_URL", "")
_AGENT_RUNNER_CANDIDATES = [
    "http://host.docker.internal:8102",
    "http://host.docker.internal:8103",
    "http://host.docker.internal:8104",
    "http://host.docker.internal:8101",
]
AGENT_RUNNER_URL = _AGENT_RUNNER_ENV_OVERRIDE or _AGENT_RUNNER_CANDIDATES[0]


def _runner_headers() -> dict:
    return {"Authorization": f"Bearer {API_SECRET}"}


async def _refresh_agent_runner_url() -> None:
    """Probe candidate runner ports and point AGENT_RUNNER_URL at whichever
    responds — runs on a schedule so a runner restarting onto a different
    port (or a new backend being added) doesn't need a manual config change.
    Skipped entirely if AGENT_RUNNER_URL was set explicitly via env var."""
    global AGENT_RUNNER_URL
    if _AGENT_RUNNER_ENV_OVERRIDE:
        return
    async with httpx.AsyncClient(timeout=3) as client:
        for candidate in _AGENT_RUNNER_CANDIDATES:
            try:
                r = await client.get(f"{candidate}/health", headers=_runner_headers())
                if r.status_code == 200:
                    AGENT_RUNNER_URL = candidate
                    return
            except Exception:
                continue


def _get_anthropic_key() -> str:
    """Read ANTHROPIC_API_KEY from env first, then secrets volume (set via UI)."""
    return os.getenv("ANTHROPIC_API_KEY") or _load_secrets().get("ANTHROPIC_API_KEY", "")


def _get_github_token() -> str:
    """Read GITHUB_TOKEN from env first, then secrets volume (set via UI).

    Unlike the module-level GITHUB_TOKEN constant (captured once at import,
    used unchanged for the process lifetime), this re-reads on every call —
    Settings -> Authentication's "update without restarting" claim was false
    for this specific value until this existed: the dashboard wrote the
    rotated token into Vault correctly, but every GitHub API call still used
    the stale constant, since _headers() read that directly. Cheap: Vault
    lookups here aren't a network call, unlike the GitHub-repo-variable-backed
    automation model, which is why this doesn't need the cache/refresh-job
    machinery that one has.
    """
    return os.getenv("GITHUB_TOKEN") or _load_secrets().get("GITHUB_TOKEN", "")


@app.post("/api/internal/anthropic-key")
async def get_anthropic_key_internal():
    """Resolve the Anthropic key for other in-stack services (agent-runner) that
    can't read orchestrator's own env/Vault directly. POST (not GET) so this goes
    through the bearer-auth middleware below, which only guards non-GET requests —
    a raw key must never sit behind an unauthenticated route, unlike GET /api/secrets
    which deliberately only ever returns presence booleans.
    """
    return {"api_key": _get_anthropic_key()}


# ── Automation model (Settings → Agents) ───────────────────────────────────────
# Single source of truth for which Claude model every direct-Anthropic-SDK call
# site uses (WO drafting, PM chat, ai-review/planning-agent/etc. GitHub Actions
# scripts, doc-writer). Persisted as a GitHub repo variable on GITHUB_REPO rather
# than an env var, so it's changeable from the dashboard without editing .env or
# redeploying — GitHub Actions scripts read the same variable directly via
# `${{ vars.ANTHROPIC_MODEL }}`, which is why this must be a repo variable and
# not something stored only in orchestrator's local volume.

DEFAULT_MODEL = "claude-sonnet-5"
_current_model: str = os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL


def _get_model() -> str:
    """Current automation model for local (non-GitHub-Actions) callers."""
    return _current_model


async def _refresh_model_cache() -> None:
    """Pick up changes made directly on GitHub (gh variable set) as well as via
    the dashboard — runs on a schedule, not just after a PUT from the UI."""
    global _current_model
    if not GITHUB_REPO:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        value = await _get_repo_variable(client, GITHUB_REPO, "ANTHROPIC_MODEL")
    if value:
        _current_model = value


@app.get("/api/settings/automation-model")
async def get_automation_model():
    return {"model": _current_model, "repo": GITHUB_REPO, "default": DEFAULT_MODEL}


class AutomationModelRequest(BaseModel):
    model: str


@app.put("/api/settings/automation-model")
async def set_automation_model(req: AutomationModelRequest):
    """Persist the model as a GitHub repo variable on GITHUB_REPO. Applies to
    local callers immediately; GitHub-Actions-run scripts pick it up on their
    next run since `vars.ANTHROPIC_MODEL` is read fresh every workflow run."""
    global _current_model
    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=422, detail="model must not be empty")
    if not GITHUB_REPO:
        raise HTTPException(status_code=409, detail="GITHUB_REPO is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        await _set_repo_variable(client, GITHUB_REPO, "ANTHROPIC_MODEL", model)
    _current_model = model
    return {"model": _current_model, "repo": GITHUB_REPO}


# ── Review model override (optional, per-purpose) ───────────────────────────
# A second, narrower knob: scripts whose job is specifically code/merge
# review (ai_review.py, merge_advisor.py) check ANTHROPIC_MODEL_REVIEW before
# falling back to the general ANTHROPIC_MODEL, then their own hardcoded
# default. Exists because one shared variable can't express "sonnet-5
# generally, but haiku for review" — found 2026-07-30 when the general
# variable silently overrode a deliberate cost/speed choice in those two
# scripts. Unlike ANTHROPIC_MODEL, nothing in this process reads this value
# for its own calls, so there's no local cache/getter to keep live — this is
# purely a GitHub-repo-variable read/write pass-through for the dashboard.

@app.get("/api/settings/review-model")
async def get_review_model():
    if not GITHUB_REPO:
        return {"model": "", "repo": GITHUB_REPO}
    async with httpx.AsyncClient(timeout=10) as client:
        value = await _get_repo_variable(client, GITHUB_REPO, "ANTHROPIC_MODEL_REVIEW")
    return {"model": value or "", "repo": GITHUB_REPO}


@app.put("/api/settings/review-model")
async def set_review_model(req: AutomationModelRequest):
    """Empty model clears the override (falls through to ANTHROPIC_MODEL, then
    each script's own hardcoded default) — unlike the general automation
    model, an empty value here is a meaningful, valid choice, not an error."""
    if not GITHUB_REPO:
        raise HTTPException(status_code=409, detail="GITHUB_REPO is not configured")
    model = req.model.strip()
    async with httpx.AsyncClient(timeout=15) as client:
        if model:
            await _set_repo_variable(client, GITHUB_REPO, "ANTHROPIC_MODEL_REVIEW", model)
        else:
            await _delete_repo_variable(client, GITHUB_REPO, "ANTHROPIC_MODEL_REVIEW")
    return {"model": model, "repo": GITHUB_REPO}


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
            r = await client.get(f"{AGENT_RUNNER_URL}/health", headers=_runner_headers())
            if r.status_code == 200:
                data = r.json()
                result["agent_runner_online"] = True
                for b in ("claude", "cursor", "codex", "gemini"):
                    result[b] = data.get("backends", {}).get(b, False)
                result["exhausted_backends"] = data.get("exhausted_backends", [])
    except Exception:
        pass
    return result


@app.get("/api/runner/agents")
async def get_runner_agents():
    """Proxy agent daemon status from the host runner (launchctl + plist state)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{AGENT_RUNNER_URL}/api/agents", headers=_runner_headers())
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {"agents": {}}


@app.put("/api/runner/agents/{name}")
async def configure_runner_agent(name: str, request: Request):
    """Create/update agent plist (API key, domain filter) and optionally start it."""
    try:
        require_runner_agent(name)
        incoming = await request.json()
        body = parse_configure_body(incoming)
    except RunnerAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if body.get("start"):
        _refuse_if_paused()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.put(f"{AGENT_RUNNER_URL}/api/agents/{name}", json=body, headers=_runner_headers())
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Agent runner unreachable: {e}")


@app.delete("/api/runner/agents/{name}")
async def remove_runner_agent(name: str):
    """Stop and uninstall an agent daemon (bootout + delete plist)."""
    try:
        require_runner_agent(name)
    except RunnerAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.delete(f"{AGENT_RUNNER_URL}/api/agents/{name}", headers=_runner_headers())
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Agent runner unreachable: {e}")


@app.post("/api/runner/agents/{name}/start")
async def start_runner_agent(name: str):
    """Bootstrap an agent LaunchAgent daemon via the host runner."""
    try:
        require_runner_agent(name)
    except RunnerAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _refuse_if_paused()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{AGENT_RUNNER_URL}/api/agents/{name}/start", headers=_runner_headers())
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Agent runner unreachable: {e}")


@app.post("/api/runner/agents/{name}/stop")
async def stop_runner_agent(name: str):
    """Bootout an agent LaunchAgent daemon via the host runner."""
    try:
        require_runner_agent(name)
    except RunnerAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{AGENT_RUNNER_URL}/api/agents/{name}/stop", headers=_runner_headers())
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Agent runner unreachable: {e}")


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
            model = _get_model()
            msg = await messages_create(
                client,
                model=model,
                max_tokens=1024,
                system=draft_system,
                messages=[{
                    "role": "user",
                    "content": f"WO number: {req.next_wo_num:03d}\n\nRequest:\n{req.description}{hint_block}",
                }],
            )
            _record_anthropic_usage(model, msg.usage.input_tokens, msg.usage.output_tokens, "plan/draft")
            text = next(b.text for b in msg.content if b.type == "text").strip()
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
                headers=_runner_headers(),
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
    {
        "name": "get_wo_status",
        "description": (
            "Get the live dispatch status of a specific WO — its current state, attempt count, "
            "last activity, and its recent thread history (claim events, review findings, errors, "
            "PR links). Use this whenever the user asks why a WO is stuck, failing, stale, or what's "
            "actually wrong with it — query_queue only shows the static plan, not live run state or "
            "failure reasons."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wo": {"type": "string", "description": "WO id, e.g. 'WO-420' or '420'"},
            },
            "required": ["wo"],
        },
    },
]


async def _execute_pm_tool(tool_name: str, tool_input: dict) -> str:
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

    if tool_name == "get_wo_status":
        raw = str(tool_input.get("wo", "")).strip().upper()
        wo_id = raw if raw.startswith("WO-") else f"WO-{raw}"
        entry = _dispatch_state.get(wo_id)
        if not entry:
            return f"{wo_id} has no dispatch history — never claimed, or fully cleared."
        result = {"dispatch": _public_dispatch_entry(entry)}
        try:
            messages = thread_store.load_thread(wo_id)[-12:]
            result["recent_thread"] = [
                {"type": m.get("type"), "author": m.get("author"), "content": (m.get("content") or "")[:500]}
                for m in messages
            ]
        except Exception as exc:
            result["recent_thread"] = f"(could not load thread: {exc})"
        return json.dumps(result, indent=2, default=str)

    # ── Action tools — audit F-06: these mirror the [DISPATCH:...]/[RESET:...]/etc.
    # regex tags parsed at the end of pm_chat() exactly, so the two mechanisms never
    # disagree about what an action actually does. The tag parser stays in place —
    # it's the only action mechanism available when PM chat falls back to a CLI
    # backend (ask() there is plain text, no tool support) — but for the Anthropic
    # API path these tools are the primary, structured way to trigger an action
    # instead of the model emitting bracketed text the server then regexes out.
    if tool_name == "dispatch_wo":
        if _factory_paused:
            return "⚠️ Factory is paused — refusing dispatch. Resume from the dashboard before starting work."
        raw_wo = str(tool_input.get("wo", "")).strip()
        backend = str(tool_input.get("backend", "")).strip()
        wo_id = raw_wo if raw_wo.startswith("WO-") else f"WO-{raw_wo}"
        try:
            await pm_dispatch_wo(wo=wo_id, backend=backend)
            runner_woke = False
            try:
                async with httpx.AsyncClient(timeout=3) as _dc:
                    await _dc.post(
                        f"{AGENT_RUNNER_URL}/dispatch",
                        json={"wo": wo_id, "backend": backend},
                        headers=_runner_headers(),
                    )
                    runner_woke = True
            except Exception:
                pass
            from datetime import UTC as _UTC, datetime as _dt
            _pm_memory.setdefault("dispatched", []).append({
                "wo": wo_id, "backend": backend,
                "date": _dt.now(_UTC).date().isoformat(),
            })
            _pm_memory["dispatched"] = _pm_memory["dispatched"][-50:]
            _save_pm_memory()
            return f"✅ {wo_id} dispatched to {backend} — {'runner woke up' if runner_woke else 'runner picks it up on next poll'}"
        except HTTPException as exc:
            return f"⚠️ Dispatch of {wo_id} failed: {exc.detail}"
        except Exception as exc:
            return f"⚠️ Dispatch of {wo_id} failed: {exc}"

    if tool_name == "reset_wo":
        raw_wo = str(tool_input.get("wo", "")).strip()
        wo_id = raw_wo if raw_wo.startswith("WO-") else f"WO-{raw_wo}"
        try:
            await reset_dispatch(wo_id)
            return f"✅ {wo_id} reset — attempt counter cleared, claimable again."
        except HTTPException as exc:
            if exc.status_code == 409:
                return f"⚠️ {wo_id} not reset: {exc.detail}"
            return f"⚠️ Reset of {wo_id} failed ({exc.status_code}): {exc.detail}"
        except Exception as exc:
            return f"⚠️ Reset of {wo_id} failed: {exc}"

    if tool_name == "merge_pr":
        pr_num = int(tool_input.get("pr_number"))
        try:
            async with httpx.AsyncClient(timeout=15) as _ac:
                pr_resp = await _ac.get(
                    f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}",
                    headers=_headers(),
                )
                if pr_resp.status_code != 200:
                    return f"⚠️ Cannot inspect PR #{pr_num} ({pr_resp.status_code}) — merge refused"
                pr_data = pr_resp.json()
                wo_num, _src = resolve_wo_for_pr_with_source(pr_data)
                priority = None
                if wo_num is not None:
                    priority = _specs_cache.get(wo_num, {}).get("priority")
                if not dispatch_control.merge_allowed_for_priority(priority):
                    return (
                        f"⚠️ Refused to merge PR #{pr_num} — risk tier is "
                        f"{priority or 'unknown'} (P2/P3 only; P0/P1 and unknown require a human)."
                    )
                mr = await _ac.put(
                    f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}/merge",
                    headers=_headers(), json={"merge_method": "squash"},
                )
                if mr.status_code in (200, 201):
                    result_msg = f"✅ Merged PR #{pr_num} (squash)"
                    try:
                        async with httpx.AsyncClient(timeout=10) as _pc:
                            pr_resp = await _pc.get(
                                f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}",
                                headers=_headers(),
                            )
                            if pr_resp.status_code == 200:
                                pr_data = pr_resp.json()
                                pr_html = pr_data.get("html_url", "")
                                wo_num, wo_src = resolve_wo_for_pr_with_source(pr_data)
                                if wo_num is not None and wo_src == "title":
                                    print(f"[orchestrator] auto-complete WO-{wo_num} skipped — title-only match, needs branch corroboration (PR #{pr_num})")
                                elif wo_num is not None and wo_src == "branch":
                                    wo_match = f"WO-{wo_num}"
                                    if _is_overridden(wo_match, "no-auto-complete"):
                                        print(f"[orchestrator] auto-complete {wo_match} skipped — override tombstone active")
                                    elif wo_match in _dispatch_state and _dispatch_state[wo_match].get("status") not in ("complete", "rejected"):
                                        _dispatch_state[wo_match]["status"] = "complete"
                                        _dispatch_state[wo_match]["completed_at"] = _utcnow()
                                        _dispatch_state[wo_match]["step"] = f"PR #{pr_num} merged via PM · 🤖 reconciler"
                                        _dispatch_state[wo_match]["pr_url"] = pr_html
                                        _dispatch_state[wo_match]["pr_number"] = pr_num
                                        _save_dispatch()
                                        _db_append_step(wo_match, "complete", step=f"PR #{pr_num} merged via PM")
                                        print(f"[orchestrator] auto-completed {wo_match} after PM merged PR #{pr_num}")
                    except Exception as ex:
                        print(f"[orchestrator] auto-complete after merge PR #{pr_num} failed: {ex}")
                    return result_msg
                elif mr.status_code == 405:
                    return f"⚠️ PR #{pr_num} not mergeable yet — CI may still be running"
                else:
                    return f"⚠️ Merge PR #{pr_num} failed ({mr.status_code}: {mr.text[:120]})"
        except Exception as exc:
            return f"⚠️ Merge PR #{pr_num} errored: {exc}"

    if tool_name == "dependabot_action":
        action = tool_input.get("action")
        pr_num = int(tool_input.get("pr_number"))
        try:
            async with httpx.AsyncClient(timeout=15) as _ac:
                if action == "rebase":
                    resp = await _ac.post(
                        f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_num}/comments",
                        headers=_headers(), json={"body": "@dependabot rebase"},
                    )
                    return (f"✅ Triggered rebase on PR #{pr_num}" if resp.status_code in (200, 201)
                            else f"⚠️ Rebase on PR #{pr_num} failed ({resp.status_code})")
                elif action == "recreate":
                    resp = await _ac.post(
                        f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_num}/comments",
                        headers=_headers(), json={"body": "@dependabot recreate"},
                    )
                    return (f"✅ Triggered recreate on PR #{pr_num} — Dependabot will open a fresh PR against main" if resp.status_code in (200, 201)
                            else f"⚠️ Recreate on PR #{pr_num} failed ({resp.status_code})")
                elif action == "approve-merge":
                    return (
                        f"⚠️ Refused approve-merge on PR #{pr_num} — "
                        "merging from PM chat is limited to merge_pr on P2/P3 WO PRs."
                    )
                return f"Unknown dependabot action: {action}"
        except Exception as exc:
            return f"⚠️ Action {action} on PR #{pr_num} errored: {exc}"

    if tool_name == "create_program":
        try:
            id_ = str(tool_input.get("id", "")).strip()
            label = str(tool_input.get("label", "")).strip() or id_
            desc = str(tool_input.get("description", "")).strip()
            _db_upsert_program(id_, label, desc)
            return f"✅ Program created: **{label}**"
        except Exception as exc:
            return f"⚠️ create_program failed: {exc}"

    if tool_name == "delete_program":
        try:
            id_ = str(tool_input.get("id", "")).strip()
            ok = _db_delete_program(id_)
            return f"✅ Program deleted: {id_}" if ok else f"⚠️ Program '{id_}' not found"
        except Exception as exc:
            return f"⚠️ delete_program failed: {exc}"

    if tool_name == "create_phase":
        try:
            id_ = str(tool_input.get("id", "")).strip()
            label = str(tool_input.get("label", "")).strip() or id_
            target_date = str(tool_input.get("target_date", "")).strip()
            _db_upsert_phase({"id": id_, "label": label, "target_date": target_date})
            return f"✅ Phase created: **{label}**"
        except Exception as exc:
            return f"⚠️ create_phase failed: {exc}"

    if tool_name == "delete_phase":
        try:
            id_ = str(tool_input.get("id", "")).strip()
            with _db() as conn:
                cur = conn.execute("DELETE FROM phases WHERE id = ?", (id_,))
                conn.commit()
            return f"✅ Phase deleted: {id_}" if cur.rowcount > 0 else f"⚠️ Phase '{id_}' not found"
        except Exception as exc:
            return f"⚠️ delete_phase failed: {exc}"

    if tool_name == "create_milestone":
        try:
            id_ = str(tool_input.get("id", "")).strip()
            label = str(tool_input.get("label", "")).strip() or id_
            target_date = str(tool_input.get("target_date", "")).strip()
            desc = str(tool_input.get("description", "")).strip()
            _db_upsert_milestone({"id": id_, "label": label, "target_date": target_date, "description": desc})
            return f"✅ Milestone created: **{label}**"
        except Exception as exc:
            return f"⚠️ create_milestone failed: {exc}"

    if tool_name == "delete_milestone":
        try:
            id_ = str(tool_input.get("id", "")).strip()
            with _db() as conn:
                cur = conn.execute("DELETE FROM milestones WHERE id = ?", (id_,))
                conn.commit()
            return f"✅ Milestone deleted: {id_}" if cur.rowcount > 0 else f"⚠️ Milestone '{id_}' not found"
        except Exception as exc:
            return f"⚠️ delete_milestone failed: {exc}"

    return f"Unknown tool: {tool_name}"


_PM_ACTION_TOOLS: list[dict] = [
    {
        "name": "dispatch_wo",
        "description": (
            "Claim a WO and dispatch it to an agent backend for implementation. Only call this "
            "when the user has explicitly confirmed they want to start the WO (said \"yes\", "
            "\"start it\", \"do it\", \"go ahead\", or similar) — never on a first mention of a WO. "
            "Before offering to dispatch or redispatch a WO the user says is stuck or failing, call "
            "get_wo_status first. If its status is 'awaiting_human' with a PR already open, do NOT "
            "call this — tell the user the PR is ready and needs their review/merge instead; "
            "dispatching again would discard that finished work (also enforced server-side)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wo": {"type": "string", "description": "WO id, e.g. 'WO-185' or '185'"},
                "backend": {"type": "string", "description": "Agent backend: claude, cursor, codex, or gemini"},
            },
            "required": ["wo", "backend"],
        },
    },
    {
        "name": "reset_wo",
        "description": (
            "Clear a WO's retry-attempt counter so it can be claimed again after hitting the retry "
            "cap (3 attempts). Use ONLY when the user explicitly asks to reset/unstick/retry a WO "
            "that get_wo_status shows is exhausted (attempt_count >= 3) — never as a first response "
            "to 'it's stuck'; always call get_wo_status first, explain what actually happened, then "
            "offer this if resetting is the right call. Do NOT call this for a WO that get_wo_status "
            "shows is 'awaiting_human' with an open PR — that WO isn't broken, it's done and waiting "
            "on a human; say so instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wo": {"type": "string", "description": "WO id, e.g. 'WO-420' or '420'"},
            },
            "required": ["wo"],
        },
    },
    {
        "name": "merge_pr",
        "description": (
            "Squash-merge a WO pull request directly (no separate GitHub review step — that would "
            "422 as a self-review). Use for WO PRs (non-Dependabot) when CI is green and the user "
            "asks to merge. Never use dependabot_action for a WO PR — it will 422."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "The PR number to merge"},
            },
            "required": ["pr_number"],
        },
    },
    {
        "name": "dependabot_action",
        "description": (
            "Act on a Dependabot PR: rebase (when CONFLICTING and rebase_blocked=false — never "
            "rebase when rebase_blocked=true, use recreate instead), recreate (opens a fresh PR "
            "from scratch), or approve-merge (when CI is green and mergeable)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["rebase", "recreate", "approve-merge"]},
                "pr_number": {"type": "integer"},
            },
            "required": ["action", "pr_number"],
        },
    },
    {
        "name": "create_program",
        "description": "Create a Program — a label WOs are assigned to, e.g. 'Launch Program'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "lowercase, hyphens only, no spaces, e.g. 'launch-program'"},
                "label": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["id", "label"],
        },
    },
    {
        "name": "delete_program",
        "description": "Delete a Program by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "create_phase",
        "description": "Create a Phase — when a WO gets dispatched. The 'now' phase runs first, then 'backlog'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "lowercase, hyphens only, no spaces"},
                "label": {"type": "string"},
                "target_date": {"type": "string", "description": "YYYY-MM-DD or empty string"},
            },
            "required": ["id", "label"],
        },
    },
    {
        "name": "delete_phase",
        "description": "Delete a Phase by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "create_milestone",
        "description": "Create a Milestone — a delivery gate. WOs that block a milestone must all complete before it's declared done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "lowercase, hyphens only, no spaces"},
                "label": {"type": "string"},
                "target_date": {"type": "string", "description": "YYYY-MM-DD or empty string"},
                "description": {"type": "string"},
            },
            "required": ["id", "label"],
        },
    },
    {
        "name": "delete_milestone",
        "description": "Delete a Milestone by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
]


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

ACTIONS — dispatch_wo, reset_wo, merge_pr, dependabot_action, create_program, delete_program,
create_phase, delete_phase, create_milestone, delete_milestone are real tools (see the tool list) —
call them directly, don't describe the action in prose instead of calling it. Each tool's own
description covers when it's appropriate; the two rules that matter most across all of them:
  - dispatch_wo and reset_wo: only call after the user has explicitly confirmed ("yes", "start it",
    "do it", "go ahead") — never on a first mention of a WO, and never for a WO that get_wo_status
    shows is "awaiting_human" with an open PR (that WO isn't broken, it's done and waiting on a
    human — say so instead of dispatching/resetting, which would discard the finished work).
  - merge_pr is for WO PRs; dependabot_action is for Dependabot PRs. Using dependabot_action's
    approve-merge on a WO PR will 422 — always use merge_pr for WO PRs instead.
Tell the user what you're about to do before calling the tool, then report the tool's result in
your reply — don't just silently call it.

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
        _b = await get_backends()
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
                _model = _get_model()
                tools = (_PM_TOOLS if LOCAL_REPO_MOUNT else []) + _PM_ACTION_TOOLS
                tool_messages = list(messages)
                tool_messages.append({"role": "user", "content": user_message if not req.images else [
                    *[{"type": "image", "source": {"type": "base64", "media_type": img.get("media_type", "image/png"), "data": img["data"]}} for img in req.images],
                    *([] if not user_message else [{"type": "text", "text": user_message}]),
                ]})
                _amsg = await messages_create(
                    _aclient,
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
                        result = await _execute_pm_tool(tc.name, tc.input)
                        tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": result})
                    tool_messages.append({"role": "user", "content": tool_results})
                    _amsg = await messages_create(
                        _aclient,
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
        # CLI backend via draft server — a full CLI subprocess invocation (cursor/claude/etc.),
        # not a direct API call, so it's meaningfully slower than the Anthropic path above.
        # A simple status question can finish in a few seconds; a request that makes the model
        # reason about a dispatch/action decision can legitimately take a couple minutes.
        try:
            async with httpx.AsyncClient(timeout=180) as _c:
                _r = await _c.post(
                    f"{AGENT_RUNNER_URL}/api/chat",
                    headers=_runner_headers(),
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
        except httpx.TimeoutException:
            # Previously uncaught — httpx.ReadTimeout (a TimeoutException subclass) propagated
            # past this except block entirely since only ConnectError was handled, crashing the
            # request as a raw 500 instead of a message the Slack bot could show the user.
            raise HTTPException(
                status_code=504,
                detail="The AI backend took too long to respond (over 3 minutes) — try a simpler "
                       "request, or ask again in a moment.",
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
                    action_results.append(
                        f"⚠️ Refused [DEPENDABOT:approve-merge:{pr_num}] — "
                        "free-text tags cannot merge. Use merge_pr on a P2/P3 WO PR, or merge in GitHub."
                    )
        except Exception as exc:
            action_results.append(f"⚠️ Action {action} on PR #{pr_num} errored: {exc}")

    if action_results:
        clean_text = clean_text + "\n\n" + "\n".join(action_results)

    # AF-15: free-text tags must not execute privileged actions. Strip them
    # and tell the operator — the structured tools (risk-tier gated) remain.
    pr_merge_pattern = re.compile(r"\[PR:merge:(\d+)\]")
    pr_merge_results: list[str] = []
    for match in pr_merge_pattern.finditer(clean_text):
        pr_num = match.group(1)
        clean_text = clean_text.replace(match.group(0), "").strip()
        pr_merge_results.append(
            f"⚠️ Refused [PR:merge:{pr_num}] from free text. "
            "Merges require the merge_pr tool (P2/P3 only) or a human."
        )

    if pr_merge_results:
        clean_text = clean_text + "\n\n" + "\n".join(pr_merge_results)

    dispatch_pattern = re.compile(r"\[DISPATCH:(WO-\d+|\d+):([\w-]+)\]")
    dispatch_results: list[str] = []
    for match in dispatch_pattern.finditer(clean_text):
        raw_wo, backend = match.group(1), match.group(2)
        wo_id = raw_wo if raw_wo.startswith("WO-") else f"WO-{raw_wo}"
        clean_text = clean_text.replace(match.group(0), "").strip()
        dispatch_results.append(
            f"⚠️ Refused [DISPATCH:{wo_id}:{backend}] from free text. "
            "Dispatch requires the dispatch_wo tool after an explicit confirmation, and the factory must not be paused."
        )

    if dispatch_results:
        clean_text = clean_text + "\n\n" + "\n".join(dispatch_results)

    reset_pattern = re.compile(r"\[RESET:(WO-\d+|\d+)\]")
    reset_results: list[str] = []
    for match in reset_pattern.finditer(clean_text):
        raw_wo = match.group(1)
        wo_id = raw_wo if raw_wo.startswith("WO-") else f"WO-{raw_wo}"
        clean_text = clean_text.replace(match.group(0), "").strip()
        reset_results.append(
            f"⚠️ Refused [RESET:{wo_id}] from free text. "
            "Reset the attempt counter from the dashboard or the reset_wo tool."
        )

    if reset_results:
        clean_text = clean_text + "\n\n" + "\n".join(reset_results)

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
                with _db() as conn:
                    cur = conn.execute("DELETE FROM phases WHERE id = ?", (id_,))
                    conn.commit()
                plan_action_results.append(f"✅ Phase deleted: {id_}" if cur.rowcount > 0 else f"⚠️ Phase '{id_}' not found")
            elif action == "DELETE_MILESTONE":
                id_ = args[0].strip()
                with _db() as conn:
                    cur = conn.execute("DELETE FROM milestones WHERE id = ?", (id_,))
                    conn.commit()
                plan_action_results.append(f"✅ Milestone deleted: {id_}" if cur.rowcount > 0 else f"⚠️ Milestone '{id_}' not found")
        except Exception as exc:
            plan_action_results.append(f"⚠️ {action} failed: {exc}")

    if plan_action_results:
        clean_text = clean_text + "\n\n" + "\n".join(plan_action_results)

    return {"type": "text", "reply": clean_text.strip(), "wo_draft": None}


# ── Run History & Audit API Endpoints ──────────────────────────────────────────

@app.get("/api/history")
async def api_get_history(
    wo: str | None = None,
    status: str | None = None,
    agent: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Retrieve durable execution run history and audit trails."""
    if wo:
        wo = wo.upper() if wo.upper().startswith("WO-") else f"WO-{wo}"
    runs = _db_get_run_history(DB_PATH, wo=wo, status=status, agent=agent, limit=limit, offset=offset)
    return {"ok": True, "count": len(runs), "history": runs}


@app.get("/api/history/metrics")
async def api_get_history_metrics():
    """Retrieve aggregate performance and reliability metrics from run history."""
    metrics = _db_get_run_metrics(DB_PATH)
    return {"ok": True, "metrics": metrics}


@app.get("/api/history/{wo_id}")
async def api_get_wo_history(wo_id: str):
    """Retrieve all execution history attempts for a specific work order."""
    wo_id = wo_id.upper() if wo_id.upper().startswith("WO-") else f"WO-{wo_id}"
    runs = _db_get_run_history(DB_PATH, wo=wo_id, limit=100)
    return {"ok": True, "wo": wo_id, "count": len(runs), "history": runs}


if __name__ == "__main__":
    uvicorn.run("orchestrator:app", host="0.0.0.0", port=API_PORT, log_level="info")
