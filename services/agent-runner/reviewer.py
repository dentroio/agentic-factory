"""
reviewer.py — Claude-powered PR gatekeeper daemon.

Polls for pending validations with a pr_url, reviews the diff with Claude, then:
  - Backend-only PRs with no API surface changes: auto-approves if code looks good
  - Backend PRs that change API routes/schemas: rebuilds containers, smoke-tests,
    then routes to human for UI verification (API contract changes can break the UI)
  - UI-change PRs: reviews code quality, posts a verification request to the thread,
    and waits for human approval — does NOT auto-approve
"""

import asyncio
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8100")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
LOCAL_REPO_PATH = os.getenv("LOCAL_REPO_PATH", "")
POLL_INTERVAL = int(os.getenv("REVIEWER_POLL_INTERVAL", "30"))
REVIEWER_NAME = "claude-reviewer"

# Files under these paths count as direct UI changes
UI_PATHS = ("frontend/src/",)
# Files under these paths are doc-writer noise — ignored in classification
NOISE_PATHS = ("frontend/public/help/",)

# Backend route files — changes here can alter the API contract consumed by the UI
API_SURFACE_PATHS = (
    "src/clarion/api/routes/",
    "src/clarion/api/schemas/",
    "services/data-service/routes/",
    "services/correlation-service/routes/",
    "services/connector-service/routes/",
    "services/clustering-service/routes/",
    "services/user-service/routes/",
    "services/gateway/routes/",
)

# Map file prefixes to the service(s) that must be rebuilt
_SERVICE_MAP: list[tuple[str, list[str]]] = [
    ("src/clarion/endpoints/correlation_engine.py", ["data-service", "correlation-service"]),
    ("src/clarion/",                                ["data-service"]),
    ("services/data-service/",                      ["data-service"]),
    ("services/correlation-service/",               ["correlation-service"]),
    ("services/connector-service/",                 ["connector-service"]),
    ("services/clustering-service/",                ["clustering-service"]),
    ("services/user-service/",                      ["user-service"]),
    ("services/gateway/",                           ["gateway"]),
    ("frontend/",                                   ["frontend"]),
]

# Track which validations we've reviewed this session (wo + requested_at)
_reviewed: set[str] = set()


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[reviewer {ts}] {msg}", flush=True)


async def _get_pending() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/validations")
            r.raise_for_status()
            return [v for v in r.json() if v.get("status") == "pending" and v.get("pr_url")]
    except Exception as e:
        _log(f"fetch validations failed: {e}")
        return []


def _pr_number(pr_url: str) -> int | None:
    m = re.search(r"/pull/(\d+)", pr_url)
    return int(m.group(1)) if m else None


def _get_pr_diff(pr_url: str) -> str:
    num = _pr_number(pr_url)
    if num is None:
        return ""
    args = ["gh", "pr", "diff", str(num)]
    if GITHUB_REPO:
        args += ["--repo", GITHUB_REPO]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        return result.stdout
    except Exception as e:
        _log(f"gh pr diff failed: {e}")
        return ""


def _changed_files(diff: str) -> list[str]:
    """Extract list of changed file paths from a unified diff."""
    files = []
    for line in diff.splitlines():
        if line.startswith("diff --git ") and " b/" in line:
            files.append(line.split(" b/", 1)[-1])
    return files


def _classify(diff: str) -> tuple[bool, bool, bool, list[str]]:
    """Return (has_ui_changes, has_api_surface_changes, has_backend_changes, services_to_rebuild)."""
    has_ui = has_api_surface = has_backend = False
    svcs: set[str] = set()

    for filepath in _changed_files(diff):
        if not filepath or any(filepath.startswith(p) for p in NOISE_PATHS):
            continue

        if any(filepath.startswith(p) for p in UI_PATHS):
            has_ui = True
        else:
            has_backend = True

        if any(filepath.startswith(p) for p in API_SURFACE_PATHS):
            has_api_surface = True

        for prefix, svc_list in _SERVICE_MAP:
            if filepath.startswith(prefix):
                svcs.update(svc_list)
                break

    return has_ui, has_api_surface, has_backend, sorted(svcs)


def _rebuild_and_smoke(repo_path: str, services: list[str]) -> tuple[bool, str]:
    """Rebuild service containers and run smoke-test. Returns (success, output)."""
    if not repo_path or not Path(repo_path).exists():
        return False, f"LOCAL_REPO_PATH not set or missing: {repo_path!r}"

    for svc in services:
        _log(f"  rebuilding {svc}...")
        result = subprocess.run(
            ["make", "build-svc", f"SVC={svc}"],
            cwd=repo_path, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return False, f"build-svc {svc} failed:\n{result.stdout[-1500:]}\n{result.stderr[-500:]}"

    _log("  running smoke-test...")
    smoke = subprocess.run(
        ["make", "smoke-test"],
        cwd=repo_path, capture_output=True, text=True, timeout=120,
    )
    passed = smoke.returncode == 0
    output = (smoke.stdout + smoke.stderr)[-2000:]
    return passed, output


def _claude_review(wo_id: str, title: str, diff: str, has_ui: bool, has_api_surface: bool) -> tuple[bool, str]:
    """Call claude -p for a focused code review. Returns (approved, notes)."""
    extra = ""
    if has_ui:
        extra += "\nNOTE: Frontend UI changes are present. Review code quality only — visual correctness verified separately."
    if has_api_surface:
        extra += "\nNOTE: API route/schema changes detected. Verify the response shapes, status codes, and field names are backward-compatible with existing UI consumers."

    prompt = f"""You are a senior engineer reviewing a PR for the Clarion network security platform.

WO: {wo_id} — {title}

Review for:
1. Security (SQL injection, XSS, hardcoded secrets, missing require_role(), SSRF)
2. Correctness (does it match the WO? missing edge cases? type errors?)
3. Clarion patterns (db.commit() after writes, parameterized queries, no bare excepts)
4. Performance (N+1 queries, unbounded result sets, blocking I/O in async handlers)
{extra}

Diff (first 14 000 chars):
{diff[:14000]}

Reply with exactly one of:
  APPROVE: <one sentence why this is ready to merge>
  REJECT: <specific, actionable issue(s) the agent must fix>

Be concise. APPROVE means the code quality is sound; UI verification is a separate step.
REJECT must say exactly what to change."""

    try:
        r = subprocess.run(
            ["claude", "-p", prompt],
            input=None, capture_output=True, text=True, timeout=180,
        )
        out = r.stdout.strip()
        if out.startswith("APPROVE"):
            return True, out[7:].lstrip(": ").strip()
        if out.startswith("REJECT"):
            return False, out[6:].lstrip(": ").strip()
        return False, f"Ambiguous response — treating as reject: {out[:300]}"
    except Exception as e:
        _log(f"claude -p failed: {e}")
        return False, f"Review error: {e}"


async def _approve(wo: str, notes: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{ORCHESTRATOR_URL}/api/validations/{wo}/approve",
                json={"decided_by": REVIEWER_NAME, "notes": notes},
            )
            return r.status_code == 200
    except Exception as e:
        _log(f"approve {wo} failed: {e}")
        return False


async def _reject(wo: str, reason: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{ORCHESTRATOR_URL}/api/validations/{wo}/reject",
                json={"decided_by": REVIEWER_NAME, "reason": reason},
            )
            return r.status_code == 200
    except Exception as e:
        _log(f"reject {wo} failed: {e}")
        return False


async def _post_thread(wo: str, content: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"{ORCHESTRATOR_URL}/api/thread/{wo}/messages",
                json={"author": REVIEWER_NAME, "role": "agent", "type": "text",
                      "content": content, "metadata": {}},
            )
    except Exception:
        pass


async def _wo_title(wo: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/queue/{wo}")
            if r.status_code == 200:
                return r.json().get("title", wo)
    except Exception:
        pass
    return wo


async def review_one(v: dict) -> None:
    wo = v["wo"]
    pr_url = v["pr_url"]

    _log(f"reviewing {wo} | {pr_url}")

    diff = _get_pr_diff(pr_url)
    if not diff:
        _log(f"{wo}: empty diff — skipping")
        return

    has_ui, has_api_surface, _, services = _classify(diff)
    title = await _wo_title(wo)
    pr_num = _pr_number(pr_url)

    # --- Code review -------------------------------------------------------
    approved, notes = _claude_review(wo, title, diff, has_ui, has_api_surface)

    if not approved:
        _log(f"{wo}: REJECT — {notes[:120]}")
        await _post_thread(wo, f"🔴 **Claude reviewer rejected**\n\n{notes}")
        await _reject(wo, notes)
        return

    # --- Determine if human verification is needed -------------------------
    # UI changes: always need visual sign-off
    # API surface changes: backend changes that alter routes/schemas the frontend
    #   consumes — we rebuild + smoke-test first, then still ask for UI verification
    needs_human = has_ui or has_api_surface

    if has_api_surface and not has_ui:
        # Rebuild affected containers and smoke-test before routing to human
        _log(f"{wo}: API surface changed — rebuilding {services} and smoke-testing")
        await _post_thread(wo, f"✅ **Code review passed** — {notes}\n\n🔄 API routes/schemas changed — rebuilding containers and running smoke-test...")

        repo = LOCAL_REPO_PATH
        if services and repo:
            build_ok, build_out = await asyncio.get_event_loop().run_in_executor(
                None, _rebuild_and_smoke, repo, services
            )
            if not build_ok:
                msg = f"🔴 **Container rebuild/smoke-test failed** after API surface change — rejecting.\n\n```\n{build_out}\n```"
                await _post_thread(wo, msg)
                await _reject(wo, f"Container rebuild failed: {build_out[:400]}")
                return
            await _post_thread(wo, f"✅ **Smoke-test passed** after rebuild of: {', '.join(services)}")
        else:
            _log(f"{wo}: LOCAL_REPO_PATH not set — skipping rebuild; routing to human anyway")

    if needs_human:
        reason = []
        if has_ui:
            reason.append("UI changes")
        if has_api_surface:
            reason.append("API contract changes (routes/schemas that the UI consumes)")
        reason_str = " + ".join(reason)

        _log(f"{wo}: code OK, {reason_str} — requesting human visual verification")
        msg = (
            f"✅ **Code review passed** — {notes}\n\n"
            f"⚠️ **Human visual verification required** — {reason_str}.\n\n"
            f"Please:\n"
            f"1. Open **https://localhost** (admin / Clarion#Admin1)\n"
            f"2. Review PR #{pr_num}: {pr_url}\n"
            f"3. Exercise the affected UI flows and confirm everything still works\n"
            f"4. Approve or reject in the **factory dashboard**"
        )
        await _post_thread(wo, msg)
        # Leave pending — human must approve
        return

    # Pure backend with no API surface changes — auto-approve
    _log(f"{wo}: APPROVE (backend-only, no API surface changes) — {notes[:120]}")
    await _post_thread(wo, f"✅ **Claude reviewer auto-approved** — {notes}")
    ok = await _approve(wo, notes)
    _log(f"{wo}: orchestrator {'accepted' if ok else 'FAILED'} approve")


async def main() -> None:
    _log(f"started — polling every {POLL_INTERVAL}s | orchestrator={ORCHESTRATOR_URL}")
    while True:
        pending = await _get_pending()
        for v in pending:
            key = f"{v['wo']}:{v.get('requested_at', '')}"
            if key in _reviewed:
                continue
            _reviewed.add(key)
            try:
                await review_one(v)
            except Exception as e:
                _log(f"error reviewing {v['wo']}: {e}")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
