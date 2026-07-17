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


async def _fetch_wo_spec(wo: str) -> dict:
    """Return the full WO queue entry (title, notes, services, etc.)."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/queue/{wo}")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


def _generate_verification_guide(
    wo_id: str,
    title: str,
    pr_url: str,
    pr_num: int | None,
    diff: str,
    wo_spec: dict,
) -> str:
    """Ask Claude to write specific, plain-English verification steps for a human reviewer."""
    changed_files = _changed_files(diff)
    ui_files  = [f for f in changed_files if any(f.startswith(p) for p in UI_PATHS)]
    api_files = [f for f in changed_files if any(f.startswith(p) for p in API_SURFACE_PATHS)]
    other_files = [f for f in changed_files if f not in ui_files and f not in api_files]

    spec_context = "\n".join(filter(None, [
        f"Title: {wo_spec.get('title', title)}",
        f"Notes: {wo_spec.get('notes', '')}" if wo_spec.get("notes") else "",
        f"Services: {wo_spec.get('services', '')}" if wo_spec.get("services") else "",
        f"Priority: {wo_spec.get('priority', '')}" if wo_spec.get("priority") else "",
    ]))

    file_summary = []
    if ui_files:
        file_summary.append(f"UI components ({len(ui_files)}): {', '.join(ui_files[:6])}")
    if api_files:
        file_summary.append(f"API routes/schemas ({len(api_files)}): {', '.join(api_files[:4])}")
    if other_files:
        file_summary.append(f"Backend ({len(other_files)}): {', '.join(other_files[:6])}")

    prompt = f"""You are writing a verification checklist for a product owner who will manually test a completed feature.
They are not a developer. Write in plain English. Be specific and concrete.

Work Order: {wo_id}
PR #{pr_num}: {pr_url}

Changed files:
{chr(10).join(file_summary) if file_summary else "No files detected."}

WO Context:
{spec_context}

Diff (first 8000 chars):
{diff[:8000]}

Write a structured verification guide with these exact sections:

## What Was Built
2-3 plain-English sentences describing what changed and why, no code or jargon.

## How to Test
Numbered steps. Start from "Open https://localhost → log in as **admin / Clarion#Admin1**".
- Name the EXACT page, menu, button, or field to interact with
- For each step, describe what **success looks like** and what **failure looks like**
- Include 3-5 meaningful steps, not generic ones like "check everything works"
- If a specific screen path applies (e.g. Devices > click endpoint > Device Profile tab), spell it out

## Quick Sanity Checks
2-3 bullet points verifying nothing else broke (navigation still works, no blank screens, no console errors).

## ✅ Approve When
One sentence: the specific condition that means this is ready to merge.

If this is a backend-only change with NO visible UI impact, say that clearly in "What Was Built"
and replace "How to Test" with a note that visual verification is not required — the code review
and CI gates already confirmed correctness."""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        text = result.stdout.strip()
        if text and len(text) > 100:
            return text
    except Exception as e:
        _log(f"generate_verification_guide failed: {e}")

    # Fallback — better than nothing
    areas = " + ".join(filter(None, [
        f"{len(ui_files)} UI file(s)" if ui_files else "",
        f"{len(api_files)} API file(s)" if api_files else "",
    ])) or "backend changes"
    return (
        f"## {wo_id}: {title}\n\n"
        f"**PR #{pr_num}:** {pr_url}\n\n"
        f"**Changes:** {areas}\n\n"
        f"**To verify:**\n"
        f"1. Open **https://localhost** → log in as **admin / Clarion#Admin1**\n"
        f"2. Navigate to the area this WO affects\n"
        f"3. Confirm the described feature works correctly\n"
        f"4. Check nothing else appears broken\n\n"
        f"Approve if everything looks correct."
    )


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
        reject_msg = (
            f"🔴 **Code review failed — agent must fix before this can merge**\n\n"
            f"**Issue found:**\n{notes}\n\n"
            f"The agent will pick this up automatically and address the problem."
        )
        await _post_thread(wo, reject_msg)
        await _reject(wo, notes)
        return

    # --- Determine if human verification is needed -------------------------
    needs_human = has_ui or has_api_surface

    if has_api_surface and not has_ui:
        _log(f"{wo}: API surface changed — rebuilding {services} and smoke-testing")
        await _post_thread(
            wo,
            f"✅ **Code review passed**\n\n"
            f"API routes or schemas changed — rebuilding the affected containers and running "
            f"smoke tests to confirm nothing broke before asking for your review...\n\n"
            f"Services being rebuilt: `{'`, `'.join(services)}`"
        )

        repo = LOCAL_REPO_PATH
        if services and repo:
            build_ok, build_out = await asyncio.get_event_loop().run_in_executor(
                None, _rebuild_and_smoke, repo, services
            )
            if not build_ok:
                # Extract just the first meaningful error line from raw output
                error_lines = [l for l in build_out.splitlines() if l.strip() and
                               any(w in l.lower() for w in ("error", "failed", "exception", "traceback"))]
                error_summary = "\n".join(error_lines[:5]) if error_lines else build_out[-400:]
                msg = (
                    f"🔴 **Container build failed** — rejecting until the agent fixes this.\n\n"
                    f"**Error:**\n```\n{error_summary}\n```\n\n"
                    f"Services that failed to rebuild: `{'`, `'.join(services)}`"
                )
                await _post_thread(wo, msg)
                await _reject(wo, f"Container rebuild failed: {error_summary[:300]}")
                return
            await _post_thread(
                wo,
                f"✅ **Containers rebuilt and smoke tests passed** — "
                f"`{'`, `'.join(services)}` are healthy."
            )
        else:
            _log(f"{wo}: LOCAL_REPO_PATH not set — skipping rebuild; routing to human anyway")

    if needs_human:
        wo_spec = await _fetch_wo_spec(wo)
        guide = _generate_verification_guide(wo, title, pr_url, pr_num, diff, wo_spec)
        _log(f"{wo}: code OK — requesting human visual verification")
        await _post_thread(
            wo,
            f"✅ **Code review passed** — ready for your sign-off.\n\n"
            f"---\n\n"
            f"{guide}\n\n"
            f"---\n\n"
            f"Use the **Approve** or **Reject** buttons in the factory dashboard when done."
        )
        return

    # Pure backend with no API surface changes — auto-approve
    _log(f"{wo}: APPROVE (backend-only, no API surface changes) — {notes[:120]}")
    await _post_thread(
        wo,
        f"✅ **Auto-approved** — backend-only change, no UI or API surface impact.\n\n"
        f"**Review summary:** {notes}\n\n"
        f"This PR will be merged automatically."
    )
    ok = await _approve(wo, notes)
    _log(f"{wo}: orchestrator {'accepted' if ok else 'FAILED'} approve")


async def _cleanup_stale_prs() -> None:
    """Close open PRs whose WO is deferred or whose dispatch entry is complete/stale-orphan."""
    if not GITHUB_REPO:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            dispatch_r = await client.get(f"{ORCHESTRATOR_URL}/api/dispatch")
            held_r = await client.get(f"{ORCHESTRATOR_URL}/api/held-wos")
            queue_r = await client.get(f"{ORCHESTRATOR_URL}/api/queue")
            if not all(r.status_code == 200 for r in (dispatch_r, held_r, queue_r)):
                return
            dispatch = dispatch_r.json()
            held = set(str(w).lstrip("WO-") for w in held_r.json())
            # Build set of WO IDs that are in deferred phase
            deferred_wos: set[str] = set()
            for entry in queue_r.json() if isinstance(queue_r.json(), list) else []:
                if entry.get("phase") == "deferred":
                    wo = str(entry.get("wo", "")).lstrip("WO-")
                    deferred_wos.add(wo)

        # Fetch open PRs
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", GITHUB_REPO, "--state", "open",
             "--json", "number,title,headRefName"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return
        import json as _json
        open_prs = _json.loads(result.stdout)

        for pr in open_prs:
            num = pr["number"]
            title = pr.get("title", "")
            branch = pr.get("headRefName", "")

            # Extract WO number from title or branch name
            m = re.search(r"WO-(\d+)", title, re.I) or re.search(r"wo[/-](\d+)", branch, re.I)
            if not m:
                continue
            wo_num = m.group(1)
            wo_id = f"WO-{wo_num}"

            # Case 1: WO is deferred → close PR
            if wo_num in deferred_wos:
                _log(f"closing PR#{num} — {wo_id} is deferred")
                subprocess.run(
                    ["gh", "pr", "close", str(num), "--repo", GITHUB_REPO,
                     "--comment", f"Auto-closed: {wo_id} moved to Deferred. PR will be reopened when WO is re-activated."],
                    capture_output=True, timeout=30,
                )
                continue

            # Case 2: dispatch entry is complete but PR is still open (orphaned)
            entry = dispatch.get(wo_id, {})
            if entry.get("status") == "complete":
                pr_url = entry.get("pr_url", "")
                # Only close if this PR is NOT the one recorded as the merged PR
                merged_pr_num = _pr_number(pr_url) if pr_url else None
                if merged_pr_num and merged_pr_num != num:
                    _log(f"closing PR#{num} — {wo_id} already completed via PR#{merged_pr_num}")
                    subprocess.run(
                        ["gh", "pr", "close", str(num), "--repo", GITHUB_REPO,
                         "--comment", f"Auto-closed: {wo_id} was completed via PR#{merged_pr_num}. This PR is an orphan."],
                        capture_output=True, timeout=30,
                    )

    except Exception as e:
        _log(f"stale PR cleanup error: {e}")


async def main() -> None:
    _log(f"started — polling every {POLL_INTERVAL}s | orchestrator={ORCHESTRATOR_URL}")
    _cleanup_cycle = 0
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
        # Run stale PR cleanup every 10 cycles (~5 min at default 30s interval)
        _cleanup_cycle += 1
        if _cleanup_cycle % 10 == 0:
            await _cleanup_stale_prs()
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
