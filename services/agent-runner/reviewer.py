"""
reviewer.py — Claude-powered PR gatekeeper daemon.

Polls for pending validations with a pr_url, reviews the diff with Claude, then:
  - Backend-only PRs: auto-approves (or rejects with feedback) based on code review
  - UI-change PRs: reviews code quality, posts a verification request to the thread,
    and waits for human approval — does NOT auto-approve
"""

import asyncio
import os
import re
import subprocess
from datetime import UTC, datetime

import httpx

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8100")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL = int(os.getenv("REVIEWER_POLL_INTERVAL", "30"))
REVIEWER_NAME = "claude-reviewer"

# Files under these paths count as UI changes requiring human visual verification
UI_PATHS = ("frontend/src/",)
# Files under these paths are doc-writer noise — ignored in classification
NOISE_PATHS = ("frontend/public/help/",)

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


def _classify(diff: str) -> tuple[bool, bool]:
    """Return (has_ui_changes, has_backend_changes)."""
    has_ui = has_backend = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            filepath = line.split(" b/", 1)[-1] if " b/" in line else ""
        elif line.startswith("+++ b/"):
            filepath = line[6:]
        else:
            continue
        if not filepath or any(filepath.startswith(p) for p in NOISE_PATHS):
            continue
        if any(filepath.startswith(p) for p in UI_PATHS):
            has_ui = True
        else:
            has_backend = True
    return has_ui, has_backend


def _claude_review(wo_id: str, title: str, diff: str, has_ui: bool) -> tuple[bool, str]:
    """Call claude -p for a focused code review. Returns (approved, notes)."""
    ui_note = (
        "\nNOTE: This PR includes frontend UI changes. Review code quality and "
        "correctness only — visual layout will be verified separately by the human."
        if has_ui else ""
    )
    prompt = f"""You are a senior engineer reviewing a PR for the Clarion network security platform.

WO: {wo_id} — {title}

Review for:
1. Security (SQL injection, XSS, hardcoded secrets, missing require_role(), SSRF)
2. Correctness (does it match the WO? missing edge cases? type errors?)
3. Clarion patterns (db.commit() after writes, parameterized queries, no bare excepts)
4. Performance (N+1 queries, unbounded result sets, blocking I/O in async handlers)
{ui_note}

Diff (first 14 000 chars):
{diff[:14000]}

Reply with exactly one of:
  APPROVE: <one sentence why this is ready to merge>
  REJECT: <specific, actionable issue(s) the agent must fix>

Be concise. APPROVE means the agent's PR will be auto-merged without further human code review.
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
        # Ambiguous — safe default is reject
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

    has_ui, _ = _classify(diff)
    title = await _wo_title(wo)
    pr_num = _pr_number(pr_url)

    approved, notes = _claude_review(wo, title, diff, has_ui)

    if not approved:
        _log(f"{wo}: REJECT — {notes[:120]}")
        await _post_thread(wo, f"🔴 **Claude reviewer rejected**\n\n{notes}")
        await _reject(wo, notes)
        return

    if has_ui:
        _log(f"{wo}: code OK but has UI changes — requesting human visual verification")
        msg = (
            f"✅ **Code review passed** — {notes}\n\n"
            f"⚠️ **Human visual verification required** — this PR contains UI changes.\n\n"
            f"Please:\n"
            f"1. Open **https://localhost** (admin / Clarion#Admin1)\n"
            f"2. Review the changes in PR #{pr_num}: {pr_url}\n"
            f"3. Verify the UI looks and behaves correctly\n"
            f"4. Approve or reject in the **factory dashboard**"
        )
        await _post_thread(wo, msg)
        # Leave pending — human must approve
        return

    # Backend-only, code approved — auto-approve
    _log(f"{wo}: APPROVE — {notes[:120]}")
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
