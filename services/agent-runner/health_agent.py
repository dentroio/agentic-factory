"""
health_agent.py — Factory Health Monitor

Runs every HEALTH_POLL_INTERVAL seconds. Autonomously detects and fixes:

  SAFE (auto-fix):
    - Local runner process died → reload launchd service
    - GitHub runner disk > DISK_WARN_PCT → SSH cleanup (diag logs + tool cache)
    - WO stuck in dispatch > STUCK_WO_HOURS with no new commits → reassign backend
    - Rejected WO sitting idle > REJECTED_RETRY_MIN → re-dispatch to different backend
    - Pending validation stale > VALIDATION_STALE_MIN → restart reviewer daemon

  ESCALATE (notify human via ntfy + thread):
    - GitHub runner disk > DISK_CRITICAL_PCT and cleanup failed
    - WO rejected > MAX_REJECTIONS times — needs human triage
    - All backends exhausted
    - Unknown crash / repeated failure
"""

import asyncio
import json
import os
import re
import socket
import subprocess
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8100")
GITHUB_REPO      = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL    = int(os.getenv("HEALTH_POLL_INTERVAL", "300"))   # 5 min
DRY_RUN          = os.getenv("HEALTH_DRY_RUN", "").lower() in ("1", "true", "yes")

# GitHub self-hosted runner SSH config
RUNNER_HOST = os.getenv("RUNNER_HOST", "192.168.10.15")
RUNNER_USER = os.getenv("RUNNER_USER", "steve")
RUNNER_PASS = os.getenv("RUNNER_PASS", "")        # used via sshpass if set
RUNNER_DIRS = ["/home/steve/actions-runner", "/home/steve/actions-runner2"]

DISK_WARN_PCT     = int(os.getenv("DISK_WARN_PCT",     "80"))
DISK_CRITICAL_PCT = int(os.getenv("DISK_CRITICAL_PCT", "95"))

STUCK_WO_HOURS       = float(os.getenv("STUCK_WO_HOURS",       "2"))
REJECTED_RETRY_MIN   = int(os.getenv("REJECTED_RETRY_MIN",      "45"))
VALIDATION_STALE_MIN = int(os.getenv("VALIDATION_STALE_MIN",    "60"))
MAX_REJECTIONS       = int(os.getenv("MAX_REJECTIONS",           "4"))

# Launchd service labels → preferred backend name
RUNNER_SERVICES: dict[str, str] = {
    "com.dentroio.factory-agent-claude":  "claude",
    "com.dentroio.factory-agent-cursor":  "cursor",
    "com.dentroio.factory-agent-codex":   "codex",
    "com.dentroio.factory-agent-gemini":  "gemini",
}
# Draft-server ports per backend (must stay in sync with plists)
RUNNER_PORTS: dict[str, int] = {
    "claude":  8102,
    "cursor":  8101,
    "codex":   8103,
    "gemini":  8104,
}

NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC  = os.getenv("NTFY_TOPIC",  "")

# Track what we've already acted on this session to avoid repeat actions
_acted: set[str] = set()


# ── Logging ───────────────────────────────────────────────────────────────────
def _log(msg: str, level: str = "info") -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    prefix = {"info": "  ", "warn": "⚠ ", "fix": "🔧", "esc": "🚨", "dry": "🌵"}.get(level, "  ")
    print(f"[health {ts}] {prefix} {msg}", flush=True)


def _dry(msg: str) -> None:
    _log(f"DRY-RUN: {msg}", "dry")


# ── Notifications ──────────────────────────────────────────────────────────────
_PRIORITY_TO_LEVEL = {"urgent": "critical", "high": "warning", "default": "info", "low": "low"}


async def _notify(title: str, body: str, priority: str = "default") -> None:
    """Push to ntfy + Slack via orchestrator, with direct ntfy fallback."""
    level = _PRIORITY_TO_LEVEL.get(priority, "info")
    sent_via_orchestrator = False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"{ORCHESTRATOR_URL}/api/notifications/alert",
                json={"title": title, "body": body, "level": level, "source": "health-agent"},
            )
            sent_via_orchestrator = r.status_code == 200
    except Exception:
        pass

    # Direct ntfy fallback if orchestrator unreachable
    if not sent_via_orchestrator and NTFY_TOPIC:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{NTFY_SERVER}/{NTFY_TOPIC}",
                    content=body.encode(),
                    headers={"Title": title, "Priority": priority, "Tags": "factory,health"},
                )
        except Exception:
            pass

    # Always log to orchestrator thread
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{ORCHESTRATOR_URL}/api/log",
                json={"source": "health-agent", "level": priority, "message": f"{title}: {body}"},
            )
    except Exception:
        pass


# ── SSH helper ────────────────────────────────────────────────────────────────
def _ssh(cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Run a command on the GitHub runner host via SSH."""
    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", "PreferredAuthentications=password",
        "-o", "PubkeyAuthentication=no",
        "-o", "GSSAPIAuthentication=no",
        "-o", "BatchMode=no",
    ]
    if RUNNER_PASS:
        args = ["sshpass", "-p", RUNNER_PASS, "ssh", *ssh_opts,
                f"{RUNNER_USER}@{RUNNER_HOST}", cmd]
    else:
        args = ["ssh", *ssh_opts, f"{RUNNER_USER}@{RUNNER_HOST}", cmd]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


# ── Orchestrator helpers ───────────────────────────────────────────────────────
async def _get(path: str) -> dict | list | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}{path}")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def _post(path: str, **kwargs) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{ORCHESTRATOR_URL}{path}", **kwargs)
            return r.status_code == 200
    except Exception:
        return False


async def _delete(path: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(f"{ORCHESTRATOR_URL}{path}")
            return r.status_code == 200
    except Exception:
        return False


# ── Check 1: Local runner health ──────────────────────────────────────────────
def _launchd_status() -> dict[str, dict]:
    """Return {label: {pid, status}} for factory runner services."""
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        statuses: dict[str, dict] = {}
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            pid_s, exit_s, label = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if label in RUNNER_SERVICES:
                statuses[label] = {
                    "pid": None if pid_s == "-" else int(pid_s),
                    "exit": int(exit_s) if exit_s != "-" else 0,
                }
        return statuses
    except Exception:
        return {}


def _reload_service(label: str) -> bool:
    plist = Path(f"~/Library/LaunchAgents/{label}.plist").expanduser()
    if not plist.exists():
        return False
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, timeout=10)
    r = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, timeout=10)
    return r.returncode == 0


async def check_local_runners() -> None:
    statuses = _launchd_status()
    for label, backend in RUNNER_SERVICES.items():
        info = statuses.get(label)
        if info is None:
            # Service not loaded at all
            act_key = f"runner-missing:{label}"
            if act_key in _acted:
                continue
            _log(f"runner {backend} not loaded in launchd", "warn")
            if DRY_RUN:
                _dry(f"would reload {label}")
            else:
                ok = _reload_service(label)
                _log(f"reloaded {label}: {'ok' if ok else 'FAILED'}", "fix")
                if ok:
                    _acted.add(act_key)
                else:
                    await _notify(f"Runner {backend} won't start",
                                  f"launchctl load failed for {label}", "high")
        elif info["pid"] is None and info["exit"] != 0:
            # Loaded but crashed
            act_key = f"runner-crashed:{label}:{info['exit']}"
            if act_key in _acted:
                continue
            _log(f"runner {backend} crashed (exit={info['exit']})", "warn")
            if DRY_RUN:
                _dry(f"would reload {label}")
            else:
                ok = _reload_service(label)
                _log(f"reloaded {label}: {'ok' if ok else 'FAILED'}", "fix")
                if ok:
                    _acted.add(act_key)
                else:
                    await _notify(f"Runner {backend} crash-looping",
                                  f"Exit code {info['exit']}. Manual intervention needed.", "urgent")


# ── Check 2: GitHub runner disk ───────────────────────────────────────────────
def _parse_disk_pct(df_line: str) -> int | None:
    """Parse use% from a `df -h` output line."""
    m = re.search(r"(\d+)%", df_line)
    return int(m.group(1)) if m else None


async def check_github_runner_disk() -> None:
    if not RUNNER_HOST:
        return
    rc, out = _ssh("df -h / | tail -1")
    if rc != 0:
        _log(f"SSH to runner host failed: {out[:100]}", "warn")
        return

    pct = _parse_disk_pct(out)
    if pct is None:
        return

    act_key = f"disk-cleaned:{RUNNER_HOST}"

    if pct < DISK_WARN_PCT:
        # Clear acted key so future fills can be addressed again
        _acted.discard(act_key)
        return

    _log(f"GitHub runner disk at {pct}% (warn={DISK_WARN_PCT}%, critical={DISK_CRITICAL_PCT}%)", "warn")

    if pct >= DISK_CRITICAL_PCT:
        await _notify("GitHub runner disk CRITICAL",
                      f"{RUNNER_HOST} at {pct}% — attempting cleanup", "urgent")

    if act_key in _acted:
        return  # already cleaned this cycle

    if DRY_RUN:
        _dry(f"would clean diag logs and duplicate tool caches on {RUNNER_HOST}")
        return

    # Clean diag logs (~500MB each)
    for d in RUNNER_DIRS:
        _ssh(f"rm -rf {d}/_diag/*", timeout=60)

    # Remove duplicate Python/Node caches from runner2 only (runner1 keeps its copy)
    if len(RUNNER_DIRS) >= 2:
        _ssh(f"rm -rf {RUNNER_DIRS[1]}/_work/_tool/Python {RUNNER_DIRS[1]}/_work/_tool/node",
             timeout=120)

    # Check result
    rc2, out2 = _ssh("df -h / | tail -1")
    pct_after = _parse_disk_pct(out2) if rc2 == 0 else pct
    _log(f"disk after cleanup: {pct_after}%", "fix")
    _acted.add(act_key)

    if pct_after >= DISK_CRITICAL_PCT:
        await _notify("GitHub runner disk still critical after cleanup",
                      f"{RUNNER_HOST} at {pct_after}% — manual cleanup needed", "urgent")
    else:
        await _notify("GitHub runner disk cleaned",
                      f"{RUNNER_HOST}: {pct}% → {pct_after}%", "low")


# ── Check 3: Stuck WOs ────────────────────────────────────────────────────────
def _worktree_last_commit_age(wo_id: str, repo_path: str) -> float | None:
    """Return hours since last commit in the WO worktree, or None if not found."""
    num = re.sub(r"[^0-9]", "", wo_id)
    worktree_base = Path(repo_path) / ".worktrees"
    candidates = list(worktree_base.glob(f"wo-{num}-*")) if worktree_base.exists() else []
    if not candidates:
        return None
    wt = candidates[0]
    try:
        r = subprocess.run(
            ["git", "-C", str(wt), "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=10,
        )
        ts = int(r.stdout.strip())
        age_h = (datetime.now().timestamp() - ts) / 3600
        return age_h
    except Exception:
        return None


BACKEND_ROTATION: dict[str, str] = {
    "claude":  "cursor",
    "cursor":  "claude",
    "codex":   "claude",
    "gemini":  "claude",
}


async def check_stuck_wos() -> None:
    dispatch = await _get("/api/dispatch")
    if not isinstance(dispatch, dict):
        return

    repo_path = os.getenv("LOCAL_REPO_PATH", "")
    now = datetime.now(UTC)

    for wo_id, entry in dispatch.items():
        if entry.get("status") != "in_progress":
            continue

        claimed_at_s = entry.get("claimed_at", "")
        try:
            claimed_at = datetime.fromisoformat(claimed_at_s.replace("Z", "+00:00"))
            hours_claimed = (now - claimed_at).total_seconds() / 3600
        except Exception:
            continue

        if hours_claimed < STUCK_WO_HOURS:
            continue

        # Check if there's any real code progress (commits beyond claim file)
        commit_age_h = _worktree_last_commit_age(wo_id, repo_path) if repo_path else None
        if commit_age_h is not None and commit_age_h < STUCK_WO_HOURS:
            continue  # has recent commits — not stuck

        act_key = f"stuck:{wo_id}:{claimed_at_s}"
        if act_key in _acted:
            continue

        backend = entry.get("backend", "")
        new_backend = BACKEND_ROTATION.get(backend, "claude")
        _log(f"{wo_id} stuck {hours_claimed:.1f}h on {backend} → reassigning to {new_backend}", "warn")

        if DRY_RUN:
            _dry(f"would release {wo_id} and re-dispatch to {new_backend}")
            continue

        released = await _delete(f"/api/dispatch/{wo_id}")
        if released:
            await _post("/api/pm/dispatch", params={"wo": wo_id, "backend": new_backend})
            _acted.add(act_key)
            _log(f"{wo_id} reassigned to {new_backend}", "fix")
            await _notify(f"{wo_id} reassigned",
                          f"Stuck {hours_claimed:.1f}h on {backend} → moved to {new_backend}", "default")


# ── Check 4: Rejected WOs not retried ─────────────────────────────────────────
async def check_rejected_wos() -> None:
    dispatch = await _get("/api/dispatch")
    if not isinstance(dispatch, dict):
        return

    validations = await _get("/api/validations")
    if not isinstance(validations, list):
        return

    # Build rejection count per WO
    rejection_counts: dict[str, int] = {}
    for v in validations:
        if v.get("status") == "rejected":
            rejection_counts[v["wo"]] = rejection_counts.get(v["wo"], 0) + 1

    now = datetime.now(UTC)
    for wo_id, entry in dispatch.items():
        if entry.get("status") != "rejected":
            continue

        last_seen_s = entry.get("last_seen") or entry.get("claimed_at", "")
        try:
            last_seen = datetime.fromisoformat(last_seen_s.replace("Z", "+00:00"))
            idle_min = (now - last_seen).total_seconds() / 60
        except Exception:
            continue

        if idle_min < REJECTED_RETRY_MIN:
            continue

        rejections = rejection_counts.get(wo_id, 0)
        act_key = f"rejected:{wo_id}:{last_seen_s}"
        if act_key in _acted:
            continue

        if rejections >= MAX_REJECTIONS:
            _log(f"{wo_id} rejected {rejections}× — escalating to human", "esc")
            _acted.add(act_key)
            await _notify(
                f"{wo_id} stuck in rejection loop",
                f"Rejected {rejections} times. Human triage needed. "
                f"Last agent: {entry.get('backend', '?')}",
                "high",
            )
            continue

        # Safe retry: release from rejected state so runner picks it back up
        backend = entry.get("backend", "")
        new_backend = BACKEND_ROTATION.get(backend, "claude")
        _log(f"{wo_id} rejected, idle {idle_min:.0f}min → re-dispatching to {new_backend}", "warn")

        if DRY_RUN:
            _dry(f"would re-dispatch {wo_id} to {new_backend}")
            continue

        released = await _delete(f"/api/dispatch/{wo_id}")
        if released:
            await _post("/api/pm/dispatch", params={"wo": wo_id, "backend": new_backend})
            _acted.add(act_key)
            _log(f"{wo_id} re-dispatched to {new_backend}", "fix")


# ── Check 5: Stale pending validations ────────────────────────────────────────
async def check_stale_validations() -> None:
    validations = await _get("/api/validations")
    if not isinstance(validations, list):
        return

    now = datetime.now(UTC)
    stale = []
    for v in validations:
        if v.get("status") != "pending":
            continue
        try:
            req = datetime.fromisoformat(v["requested_at"].replace("Z", "+00:00"))
            age_min = (now - req).total_seconds() / 60
            if age_min > VALIDATION_STALE_MIN:
                stale.append((v["wo"], age_min))
        except Exception:
            continue

    if not stale:
        return

    act_key = f"stale-validations:{','.join(w for w, _ in stale)}"
    if act_key in _acted:
        return

    _log(f"{len(stale)} validations stale > {VALIDATION_STALE_MIN}min: "
         f"{[w for w, _ in stale]}", "warn")

    if DRY_RUN:
        _dry("would restart reviewer daemon")
        return

    # Restart the reviewer daemon
    subprocess.run(["pkill", "-f", "reviewer.py"], capture_output=True)
    import time; time.sleep(2)

    reviewer_script = Path(__file__).parent / "run-reviewer.sh"
    if reviewer_script.exists():
        subprocess.Popen(
            ["bash", str(reviewer_script)],
            stdout=open(Path.home() / "Library/Logs/factory-agent/out-reviewer.log", "a"),
            stderr=subprocess.STDOUT,
        )
        _log("reviewer daemon restarted", "fix")
        _acted.add(act_key)
    else:
        await _notify("Stale validations — reviewer won't restart",
                      f"{len(stale)} pending validations > {VALIDATION_STALE_MIN}min. "
                      f"run-reviewer.sh not found.", "high")


# ── Check 6: Backend exhaustion ───────────────────────────────────────────────
async def check_backends() -> None:
    backends = await _get("/api/backends")
    if not isinstance(backends, dict):
        return
    exhausted = backends.get("exhausted_backends", [])
    if exhausted:
        act_key = f"exhausted:{','.join(sorted(exhausted))}"
        if act_key not in _acted:
            _log(f"backends exhausted: {exhausted}", "esc")
            _acted.add(act_key)
            await _notify("Factory backends exhausted",
                          f"These backends hit quota/rate limits: {exhausted}. "
                          f"Check usage dashboard.", "high")
    else:
        # Clear exhaustion alerts so they can fire again later
        for key in list(_acted):
            if key.startswith("exhausted:"):
                _acted.discard(key)


# ── Main loop ─────────────────────────────────────────────────────────────────
async def main() -> None:
    mode = "DRY-RUN" if DRY_RUN else "LIVE"
    _log(f"started [{mode}] — polling every {POLL_INTERVAL}s | orchestrator={ORCHESTRATOR_URL}")

    # Fetch ntfy config from orchestrator if not set via env
    global NTFY_TOPIC, NTFY_SERVER
    if not NTFY_TOPIC:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{ORCHESTRATOR_URL}/api/notifications/config")
                if r.status_code == 200:
                    cfg = r.json()
                    NTFY_TOPIC  = cfg.get("ntfy_topic", "")
                    NTFY_SERVER = cfg.get("ntfy_server", NTFY_SERVER)
        except Exception:
            pass

    while True:
        try:
            await check_local_runners()
            await check_github_runner_disk()
            await check_stuck_wos()
            await check_rejected_wos()
            await check_stale_validations()
            await check_backends()
        except Exception as e:
            _log(f"health check cycle error: {e}", "warn")

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
