import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
CI_FAIL_THRESHOLD = int(os.getenv("CI_FAIL_THRESHOLD", "60"))
CI_STUCK_THRESHOLD = int(os.getenv("CI_STUCK_THRESHOLD", "45"))
STALE_DAYS = int(os.getenv("STALE_DAYS", "7"))
ANCIENT_DAYS = int(os.getenv("ANCIENT_DAYS", "14"))
QUEUE_WARN_DEPTH = int(os.getenv("QUEUE_WARN_DEPTH", "5"))
POST_COMMENTS = os.getenv("POST_COMMENTS", "false").lower() == "true"
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", "/data/watchdog.json"))


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _minutes_since(dt: datetime | None) -> float:
    if not dt:
        return 0.0
    return (datetime.now(UTC) - dt).total_seconds() / 60


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None):
    url = f"https://api.github.com{path}"
    resp = await client.get(url, headers=_headers(), params=params or {})
    resp.raise_for_status()
    return resp.json()


async def _fetch_open_prs(client: httpx.AsyncClient) -> list[dict]:
    return await _get(client, f"/repos/{GITHUB_REPO}/pulls", {"state": "open", "per_page": 100})


async def _fetch_pr_checks(client: httpx.AsyncClient, pr_number: int) -> list[dict]:
    commits = await _get(client, f"/repos/{GITHUB_REPO}/pulls/{pr_number}/commits")
    if not commits:
        return []
    sha = commits[-1]["sha"]
    data = await _get(client, f"/repos/{GITHUB_REPO}/commits/{sha}/check-runs", {"per_page": 100})
    return data.get("check_runs", [])


async def _fetch_runners(client: httpx.AsyncClient) -> list[dict]:
    data = await _get(client, f"/repos/{GITHUB_REPO}/actions/runners")
    return data.get("runners", [])


async def _fetch_queue_depth(client: httpx.AsyncClient) -> int:
    queued = await _get(client, f"/repos/{GITHUB_REPO}/actions/runs", {"status": "queued", "per_page": 30})
    in_progress = await _get(client, f"/repos/{GITHUB_REPO}/actions/runs", {"status": "in_progress", "per_page": 30})
    return len(queued.get("workflow_runs", [])) + len(in_progress.get("workflow_runs", []))


def _evaluate_pr(pr: dict, checks: list[dict], now_str: str, prev: dict) -> tuple[dict, list[dict]]:
    number = pr["number"]
    title = pr["title"]
    created_at = _parse_dt(pr.get("created_at"))
    age_hours = _minutes_since(created_at) / 60
    age_days = age_hours / 24
    mergeable_state = pr.get("mergeable_state", "unknown")
    auto_merge = pr.get("auto_merge") is not None

    alerts: list[dict] = []
    rules_triggered: list[str] = []

    # Determine overall CI state
    conclusions = [c.get("conclusion") for c in checks if c.get("conclusion")]
    statuses = [c.get("status") for c in checks]
    if any(c in ("failure", "timed_out") for c in conclusions):
        ci_state = "failure"
    elif any(s in ("queued", "in_progress") for s in statuses):
        ci_state = "pending"
    elif conclusions and all(c == "success" for c in conclusions):
        ci_state = "success"
    else:
        ci_state = "unknown"

    ci_duration_minutes = None

    # Rule: CI failing too long
    if ci_state == "failure":
        failing = [c for c in checks if c.get("conclusion") in ("failure", "timed_out")]
        if failing:
            earliest = min(
                (_parse_dt(c.get("completed_at")) for c in failing if c.get("completed_at")),
                default=None,
            )
            if earliest:
                fail_mins = _minutes_since(earliest)
                ci_duration_minutes = int(fail_mins)
                if fail_mins >= CI_FAIL_THRESHOLD:
                    rules_triggered.append("ci-failing-long")
                    key = f"{number}:ci-failing-long"
                    first_seen = prev.get(key, {}).get("first_seen", now_str)
                    alerts.append({
                        "pr_number": number,
                        "pr_title": title,
                        "rule": "ci-failing-long",
                        "severity": "error",
                        "message": f"CI failing for {int(fail_mins)}m",
                        "detail": ", ".join(c["name"] for c in failing[:2]),
                        "first_seen": first_seen,
                        "last_checked": now_str,
                    })

    # Rule: CI stuck
    if ci_state == "pending":
        for c in checks:
            if c.get("status") in ("queued", "in_progress") and c.get("started_at"):
                started = _parse_dt(c["started_at"])
                stuck_mins = _minutes_since(started)
                if stuck_mins >= CI_STUCK_THRESHOLD:
                    rules_triggered.append("ci-stuck")
                    key = f"{number}:ci-stuck"
                    first_seen = prev.get(key, {}).get("first_seen", now_str)
                    alerts.append({
                        "pr_number": number,
                        "pr_title": title,
                        "rule": "ci-stuck",
                        "severity": "warning",
                        "message": f"CI stuck ({c['status']}) for {int(stuck_mins)}m",
                        "detail": c["name"],
                        "first_seen": first_seen,
                        "last_checked": now_str,
                    })
                    break

    # Rule: CI never ran
    if not checks and age_hours >= (10 / 60):
        rules_triggered.append("ci-never-ran")
        alerts.append({
            "pr_number": number,
            "pr_title": title,
            "rule": "ci-never-ran",
            "severity": "warning",
            "message": f"No CI checks triggered ({int(age_hours * 60)}m after opening)",
            "detail": "Check workflow trigger conditions",
            "first_seen": now_str,
            "last_checked": now_str,
        })

    # Rule: merge conflict
    if mergeable_state == "dirty":
        rules_triggered.append("merge-conflict")
        alerts.append({
            "pr_number": number,
            "pr_title": title,
            "rule": "merge-conflict",
            "severity": "error",
            "message": "Merge conflict with base branch",
            "detail": "Branch must be rebased or merged",
            "first_seen": now_str,
            "last_checked": now_str,
        })

    # Rule: auto-merge blocked by CI
    if auto_merge and ci_state == "failure":
        rules_triggered.append("auto-merge-blocked")
        alerts.append({
            "pr_number": number,
            "pr_title": title,
            "rule": "auto-merge-blocked",
            "severity": "warning",
            "message": "Auto-merge queued but CI is failing",
            "detail": "PR will not merge until CI passes",
            "first_seen": now_str,
            "last_checked": now_str,
        })

    # Rule: stale / ancient
    if age_days >= ANCIENT_DAYS:
        rules_triggered.append("pr-ancient")
        alerts.append({
            "pr_number": number,
            "pr_title": title,
            "rule": "pr-ancient",
            "severity": "error",
            "message": f"PR open for {int(age_days)} days",
            "detail": "Needs attention or closure",
            "first_seen": now_str,
            "last_checked": now_str,
        })
    elif age_days >= STALE_DAYS:
        rules_triggered.append("pr-stale")
        alerts.append({
            "pr_number": number,
            "pr_title": title,
            "rule": "pr-stale",
            "severity": "warning",
            "message": f"PR open {int(age_days)} days with no merge",
            "detail": "Consider reviewing or closing",
            "first_seen": now_str,
            "last_checked": now_str,
        })

    health = {
        "number": number,
        "title": title,
        "age_hours": round(age_hours, 1),
        "ci_state": ci_state,
        "ci_duration_minutes": ci_duration_minutes,
        "mergeable": mergeable_state not in ("dirty", "blocked"),
        "auto_merge": auto_merge,
        "rules_triggered": rules_triggered,
    }
    return health, alerts


async def _maybe_post_comment(client: httpx.AsyncClient, pr_number: int, body: str) -> None:
    if not POST_COMMENTS:
        return
    existing = await _get(client, f"/repos/{GITHUB_REPO}/issues/{pr_number}/comments", {"per_page": 100})
    bot_comment = next((c for c in existing if "watchdog" in c.get("body", "").lower()), None)
    if bot_comment:
        await client.patch(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues/comments/{bot_comment['id']}",
            headers=_headers(),
            json={"body": body},
        )
    else:
        await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_number}/comments",
            headers=_headers(),
            json={"body": body},
        )


async def poll() -> None:
    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Load previous alert state for first_seen tracking
    prev: dict = {}
    if OUTPUT_PATH.exists():
        try:
            old = json.loads(OUTPUT_PATH.read_text())
            for a in old.get("alerts", []):
                if a.get("pr_number") and a.get("rule"):
                    prev[f"{a['pr_number']}:{a['rule']}"] = a
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            prs, runners, queue_depth = await asyncio.gather(
                _fetch_open_prs(client),
                _fetch_runners(client),
                _fetch_queue_depth(client),
            )
        except Exception as e:
            print(f"[watchdog] API error during initial fetch: {e}")
            return

        pr_health: list[dict] = []
        all_alerts: list[dict] = []

        for pr in prs:
            try:
                checks = await _fetch_pr_checks(client, pr["number"])
                health, alerts = _evaluate_pr(pr, checks, now_str, prev)
                pr_health.append(health)
                all_alerts.extend(alerts)

                # Post comment for new error-level alerts
                error_alerts = [a for a in alerts if a["severity"] == "error"]
                for alert in error_alerts:
                    key = f"{pr['number']}:{alert['rule']}"
                    if key not in prev:
                        body = f"**[Factory Watchdog]** {alert['message']}\n\n{alert['detail']}"
                        await _maybe_post_comment(client, pr["number"], body)
            except Exception as e:
                print(f"[watchdog] Error on PR #{pr['number']}: {e}")

        # Runner saturation
        runners_online = sum(1 for r in runners if r.get("status") == "online")
        runners_busy = sum(1 for r in runners if r.get("busy"))
        if runners_online > 0 and runners_busy >= runners_online:
            all_alerts.append({
                "pr_number": None,
                "pr_title": None,
                "rule": "runners-all-busy",
                "severity": "info",
                "message": f"All {runners_online} runner(s) busy",
                "detail": ", ".join(r["name"] for r in runners if r.get("busy")),
                "first_seen": now_str,
                "last_checked": now_str,
            })

        # Queue depth
        if queue_depth >= QUEUE_WARN_DEPTH:
            all_alerts.append({
                "pr_number": None,
                "pr_title": None,
                "rule": "queue-depth",
                "severity": "warning",
                "message": f"GitHub Actions: {queue_depth} workflow runs queued/running",
                "detail": "Runners may be saturated (each PR triggers multiple checks)",
                "first_seen": now_str,
                "last_checked": now_str,
            })

        # Dedup: one alert per (pr, rule)
        seen: set = set()
        deduped: list[dict] = []
        for a in all_alerts:
            key = f"{a['pr_number']}:{a['rule']}"
            if key not in seen:
                seen.add(key)
                deduped.append(a)

        errors = sum(1 for a in deduped if a["severity"] == "error")
        warnings = sum(1 for a in deduped if a["severity"] == "warning")
        healthy = sum(1 for p in pr_health if not p["rules_triggered"])

        output = {
            "generated_at": now_str,
            "poll_interval_seconds": POLL_INTERVAL,
            "summary": {
                "total_open_prs": len(prs),
                "healthy": healthy,
                "warnings": warnings,
                "errors": errors,
                "runners_online": runners_online,
                "runners_busy": runners_busy,
                "queue_depth": queue_depth,
            },
            "alerts": sorted(deduped, key=lambda a: {"error": 0, "warning": 1, "info": 2}.get(a["severity"], 3)),
            "pr_health": pr_health,
            "runner_health": {
                "runners": [{"name": r["name"], "status": r.get("status"), "busy": r.get("busy", False)} for r in runners],
                "queue_depth": queue_depth,
            },
        }

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(output, indent=2))
        print(f"[watchdog] {now_str} — {len(prs)} PRs checked, {errors} errors, {warnings} warnings, queue={queue_depth}")


async def main() -> None:
    print(f"[watchdog] Starting — repo={GITHUB_REPO}, interval={POLL_INTERVAL}s")
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[watchdog] ERROR: GITHUB_TOKEN and GITHUB_REPO must be set")
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
