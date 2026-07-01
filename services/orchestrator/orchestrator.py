import asyncio
import base64
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
MAX_PARALLEL_WOS = int(os.getenv("MAX_PARALLEL_WOS", "2"))
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
RUNS_PATH = os.getenv("RUNS_PATH", "docs/factory/runs")
DAILY_SUMMARY_HOUR = os.getenv("DAILY_SUMMARY_HOUR", "")
SUMMARY_ISSUE_NUMBER = os.getenv("SUMMARY_ISSUE_NUMBER", "")

OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", "/data/orchestrator.json"))
WATCHDOG_PATH = Path(os.getenv("WATCHDOG_PATH", "/watchdog/watchdog.json"))

_last_summary_day: int = -1


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


# ── WO spec parsing ──────────────────────────────────────────────────────────

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
    m = re.search(r"^# WO-\d+ — (.+)$", content, re.MULTILINE)
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
    return "done" in s or "complete" in s or "✅" in status


def _is_in_progress(status: str) -> bool:
    s = status.lower()
    return "progress" in s or "🔄" in s


def _is_blocked(status: str) -> bool:
    s = status.lower()
    return "blocked" in s or "🔴" in s


# ── GitHub API helpers ───────────────────────────────────────────────────────

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
        nums: set[int] = set()
        for b in branches:
            m = re.match(r"wo/(\d+)-", b["name"])
            if m:
                nums.add(int(m.group(1)))
        return nums
    except Exception:
        return set()


async def _fetch_open_pr_wos(client: httpx.AsyncClient) -> set[int]:
    try:
        prs = await _get(client, f"/repos/{GITHUB_REPO}/pulls", {"state": "open", "per_page": 100})
        nums: set[int] = set()
        for pr in prs:
            m = re.search(r"WO-(\d+)", pr.get("title", ""))
            if m:
                nums.add(int(m.group(1)))
        return nums
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


# ── Dependency graph ─────────────────────────────────────────────────────────

def _resolve_dependencies(specs: dict[int, dict], done_wos: set[int]) -> tuple[list[dict], list[dict], list[str]]:
    """Return (dispatch_queue, holding_queue, cycle_warnings)."""
    dispatch: list[dict] = []
    holding: list[dict] = []
    warnings: list[str] = []

    # Detect circular dependencies (simple cycle detection)
    def has_cycle(num: int, visiting: set[int]) -> bool:
        if num in visiting:
            return True
        deps = specs.get(num, {}).get("depends_on", [])
        visiting = visiting | {num}
        return any(has_cycle(d, visiting) for d in deps if d in specs)

    for num, spec in sorted(specs.items(), key=lambda x: (x[1]["priority"], x[0])):
        if _is_done(spec["status"]):
            continue

        deps = spec.get("depends_on", [])

        # Circular dependency check
        if has_cycle(num, set()):
            warnings.append(f"WO-{num} has a circular dependency — skipping")
            continue

        unmet = [d for d in deps if d not in done_wos]
        if unmet:
            holding.append({
                "wo": num,
                "title": spec["title"],
                "priority": spec["priority"],
                "dependencies_met": False,
                "blocked_by": unmet,
                "reason": f"Waiting on WO-{', WO-'.join(str(d) for d in unmet)}",
            })
        else:
            dispatch.append({
                "wo": num,
                "title": spec["title"],
                "priority": spec["priority"],
                "effort": spec["effort"],
                "dependencies_met": True,
                "recommended_action": "start",
                "reason": "Open, dependencies met" if deps else "Open, no dependencies",
            })

    # Sort dispatch by priority then WO number
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    dispatch.sort(key=lambda x: (priority_order.get(x["priority"], 9), x["wo"]))

    return dispatch[:MAX_PARALLEL_WOS * 3], holding, warnings


# ── Daily summary ────────────────────────────────────────────────────────────

async def _maybe_post_summary(client: httpx.AsyncClient, output: dict) -> None:
    global _last_summary_day
    if not DAILY_SUMMARY_HOUR or not SUMMARY_ISSUE_NUMBER:
        return
    now = datetime.now(UTC)
    if now.hour != int(DAILY_SUMMARY_HOUR):
        return
    if now.day == _last_summary_day:
        return

    board = output["board_summary"]
    dispatch = output["dispatch_queue"]
    active = output["active_work"]

    lines = [
        f"## Factory Daily Summary — {now.strftime('%a %b %d, %Y')}",
        "",
        f"**Board:** {board['open']} Open · {board['in_progress']} In Progress · "
        f"{board['in_review']} In Review · {board['blocked']} Blocked · {board['done_this_week']} done this week",
        "",
    ]

    if dispatch:
        lines.append("**Ready to start:**")
        for item in dispatch[:5]:
            lines.append(f"- WO-{item['wo']} ({item['priority']}): {item['title']}")
        lines.append("")

    if active:
        lines.append("**In Progress:**")
        for item in active:
            agent = f" — {item['agent']}, {item['step']}" if item.get("agent") else ""
            lines.append(f"- WO-{item['wo']}: {item['title']}{agent}")
        lines.append("")

    holding = output.get("holding_queue", [])
    if holding:
        lines.append("**Blocked (unmet deps):**")
        for item in holding[:5]:
            lines.append(f"- WO-{item['wo']} depends on WO-{', WO-'.join(str(d) for d in item['blocked_by'])}")
        lines.append("")

    if output.get("recommendations"):
        lines.append("**Recommendations:**")
        for r in output["recommendations"][:5]:
            lines.append(f"- {r}")

    body = "\n".join(lines)

    try:
        comments = await _get(client, f"/repos/{GITHUB_REPO}/issues/{SUMMARY_ISSUE_NUMBER}/comments", {"per_page": 100})
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
        print(f"[orchestrator] Posted daily summary to issue #{SUMMARY_ISSUE_NUMBER}")
    except Exception as e:
        print(f"[orchestrator] Failed to post summary: {e}")


# ── Load watchdog data ───────────────────────────────────────────────────────

def _load_watchdog() -> dict | None:
    if not WATCHDOG_PATH.exists():
        return None
    try:
        return json.loads(WATCHDOG_PATH.read_text())
    except Exception:
        return None


# ── Main poll ────────────────────────────────────────────────────────────────

async def poll() -> None:
    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    async with httpx.AsyncClient(timeout=20) as client:
        specs, active_branch_wos, pr_wos, merged_this_week = await asyncio.gather(
            _fetch_wo_specs(client),
            _fetch_active_branches(client),
            _fetch_open_pr_wos(client),
            _fetch_merged_wo_count_this_week(client),
        )

    done_wos = {num for num, s in specs.items() if _is_done(s["status"])}
    in_progress_wos = active_branch_wos - pr_wos - done_wos
    in_review_wos = pr_wos - done_wos
    open_wos = {num for num, s in specs.items()
                if not _is_done(s["status"]) and num not in active_branch_wos and num not in pr_wos}
    blocked_wos = {num for num, s in specs.items() if _is_blocked(s["status"])}

    dispatch_queue, holding_queue, cycle_warnings = _resolve_dependencies(
        {num: s for num, s in specs.items() if num in open_wos},
        done_wos,
    )

    # Active work details
    active_work = []
    for num in sorted(in_progress_wos):
        spec = specs.get(num, {})
        active_work.append({
            "wo": num,
            "title": spec.get("title", f"WO-{num}"),
            "branch": f"wo/{num}-*",
            "agent": None,
            "step": None,
        })
    for num in sorted(in_review_wos):
        spec = specs.get(num, {})
        active_work.append({
            "wo": num,
            "title": spec.get("title", f"WO-{num}"),
            "branch": None,
            "pr": True,
            "agent": None,
            "step": None,
        })

    # Recommendations
    watchdog = _load_watchdog()
    recommendations: list[str] = []
    if dispatch_queue:
        top = dispatch_queue[0]
        recommendations.append(f"WO-{top['wo']} ({top['priority']}) is ready to start: {top['title']}")
    if watchdog:
        errors = watchdog.get("summary", {}).get("errors", 0)
        if errors:
            recommendations.append(f"{errors} PR(s) have errors — check the CI View for details")
        runners_busy = watchdog.get("summary", {}).get("runners_busy", 0)
        runners_online = watchdog.get("summary", {}).get("runners_online", 0)
        if runners_online > 0 and runners_busy >= runners_online:
            recommendations.append("All runners busy — hold off starting new WOs until a runner frees up")
    if len(in_progress_wos) >= MAX_PARALLEL_WOS:
        recommendations.append(f"At parallel WO limit ({MAX_PARALLEL_WOS}) — complete in-progress work before starting more")
    if cycle_warnings:
        recommendations.extend(cycle_warnings)

    output = {
        "generated_at": now_str,
        "poll_interval_seconds": POLL_INTERVAL,
        "max_parallel_wos": MAX_PARALLEL_WOS,
        "runner_capacity": {
            "total": watchdog.get("summary", {}).get("runners_online", 0) if watchdog else 0,
            "busy": watchdog.get("summary", {}).get("runners_busy", 0) if watchdog else 0,
            "available": max(0, watchdog.get("summary", {}).get("runners_online", 0) -
                           watchdog.get("summary", {}).get("runners_busy", 0)) if watchdog else 0,
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
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"[orchestrator] {now_str} — {len(specs)} WOs, {len(dispatch_queue)} dispatchable, "
          f"{len(in_progress_wos)} in-progress, {len(in_review_wos)} in-review")

    async with httpx.AsyncClient(timeout=20) as client:
        await _maybe_post_summary(client, output)


async def main() -> None:
    print(f"[orchestrator] Starting — repo={GITHUB_REPO}, interval={POLL_INTERVAL}s, max_parallel={MAX_PARALLEL_WOS}")
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[orchestrator] ERROR: GITHUB_TOKEN and GITHUB_REPO must be set")
        return

    await poll()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(poll, "interval", seconds=POLL_INTERVAL)
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
