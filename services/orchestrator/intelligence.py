"""
intelligence.py — Factory Intelligence Loop

Runs on a configurable interval (default 10 min) and autonomously handles
recurring problems that previously required human intervention:

  1. Major-version Dependabot PRs → auto-close + suppress future bumps
  2. PRs stuck with merge conflicts (DIRTY) → create factory WO to resolve
  3. CI failing > FAILURE_THRESHOLD_MINUTES → LLM diagnoses, creates WO or re-triggers
  4. Ghost dispatch entries (claimed/in_progress but stale) → re-queue

All actions are logged to _last_run so the /api/intelligence/status endpoint
can show what happened.
"""

from __future__ import annotations

import json
import os
import re
import uuid
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

import httpx
from wo_resolver import resolve_wo_for_pr  # noqa: F401 — available for callers

FAILURE_THRESHOLD_MINUTES = 90
GHOST_THRESHOLD_HOURS = 3
GHOST_ESCALATE_HOURS = 24
_DEDUP_TTL_HOURS = 24

_DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
_ACTED_ON_PATH = _DATA_DIR / "intelligence_acted_on.json"

# Dedup dict: keyed by "action:identifier", value is ISO timestamp string.
# Loaded from disk on startup; flushed after each pass so it survives restarts.
_acted_on: dict[str, str] = {}


def _load_acted_on() -> None:
    try:
        if _ACTED_ON_PATH.exists():
            _acted_on.update(json.loads(_ACTED_ON_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass


def _flush_acted_on() -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _ACTED_ON_PATH.write_text(json.dumps(_acted_on, indent=2), encoding="utf-8")
    except Exception:
        pass


_load_acted_on()


def _dedup_key(action: str, identifier: str) -> str:
    return f"{action}:{identifier}"


def _already_acted(action: str, identifier: str) -> bool:
    key = _dedup_key(action, identifier)
    ts_str = _acted_on.get(key)
    if ts_str is None:
        return False
    try:
        ts = datetime.fromisoformat(ts_str)
    except Exception:
        del _acted_on[key]
        return False
    if (datetime.now(UTC) - ts).total_seconds() > _DEDUP_TTL_HOURS * 3600:
        del _acted_on[key]
        return False
    return True


def _mark_acted(action: str, identifier: str) -> None:
    _acted_on[_dedup_key(action, identifier)] = datetime.now(UTC).isoformat()


def _gh_headers(token: str) -> dict:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }


async def _gh_get(client: httpx.AsyncClient, token: str, path: str, params: dict | None = None) -> dict | list:
    url = f"https://api.github.com{path}"
    r = await client.get(url, headers=_gh_headers(token), params=params or {})
    r.raise_for_status()
    return r.json()


async def _gh_post(client: httpx.AsyncClient, token: str, path: str, body: dict) -> dict:
    url = f"https://api.github.com{path}"
    r = await client.post(url, headers=_gh_headers(token), json=body)
    r.raise_for_status()
    return r.json()


async def _gh_patch(client: httpx.AsyncClient, token: str, path: str, body: dict) -> dict:
    url = f"https://api.github.com{path}"
    r = await client.patch(url, headers=_gh_headers(token), json=body)
    r.raise_for_status()
    return r.json()


# ── Dependabot: major version detection ───────────────────────────────────────

def _parse_major_bumps(pr_body: str) -> list[str]:
    """Return list of package names that are being bumped across a major version."""
    bumps = []
    for m in re.finditer(
        r"Updates?\s+`([^`]+)`\s+from\s+(\d+)\.\S+\s+to\s+(\d+)\.\S+",
        pr_body or "",
        re.IGNORECASE,
    ):
        pkg, old_major, new_major = m.group(1), int(m.group(2)), int(m.group(3))
        if new_major > old_major:
            bumps.append(pkg)
    return bumps


# ── CI failure helpers ─────────────────────────────────────────────────────────

def _minutes_since(iso_ts: str) -> float:
    try:
        t = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(UTC) - t).total_seconds() / 60
    except Exception:
        return 0.0


async def _get_check_failure_summary(
    client: httpx.AsyncClient, token: str, repo: str, sha: str
) -> str:
    """Return a condensed summary of failing check output for LLM diagnosis."""
    try:
        data = await _gh_get(client, token, f"/repos/{repo}/commits/{sha}/check-runs", {"per_page": 50})
        runs = data.get("check_runs", []) if isinstance(data, dict) else []
        lines = []
        for run in runs:
            if run.get("conclusion") == "failure":
                name = run.get("name", "unknown")
                summary = (run.get("output") or {}).get("summary") or ""
                text = (run.get("output") or {}).get("text") or ""
                # Trim to avoid blowing out the LLM context
                combined = (summary + "\n" + text).strip()[:1500]
                if combined:
                    lines.append(f"## {name}\n{combined}")
        return "\n\n".join(lines) or "No detailed output captured."
    except Exception as e:
        return f"Could not fetch check details: {e}"


# ── LLM diagnosis ─────────────────────────────────────────────────────────────

async def _llm_diagnose_ci_failure(
    anthropic_key: str,
    pr_number: int,
    pr_title: str,
    failure_summary: str,
    repo: str,
) -> dict:
    """
    Ask Claude to diagnose a CI failure and recommend an action.
    Returns: {action, priority, wo_title, wo_description, summary}
    """
    if not anthropic_key:
        return {"action": "ignore", "summary": "No Anthropic key — skipping LLM diagnosis"}

    system = (
        "You are the intelligence layer of an AI software factory. "
        "A CI check has been failing for over 90 minutes on a pull request. "
        "Diagnose the failure and decide what to do. "
        "Reply ONLY with valid JSON matching this schema:\n"
        "{\n"
        '  "action": "create_wo" | "rerun" | "ignore",\n'
        '  "priority": "P0" | "P1" | "P2",\n'
        '  "wo_title": "short title if action=create_wo",\n'
        '  "wo_description": "2-4 sentence description if action=create_wo",\n'
        '  "summary": "one sentence explaining your decision"\n'
        "}\n\n"
        "Guidelines:\n"
        "- create_wo: the failure is a real code/config bug that needs an agent to fix\n"
        "- rerun: the failure looks transient (network error, runner issue, flaky test)\n"
        "- ignore: CI is still running, or the failure is expected/in-progress work\n"
        "- For create_wo, set priority based on severity (P0=blocking, P1=important, P2=normal)"
    )

    user = (
        f"Repository: {repo}\n"
        f"PR #{pr_number}: {pr_title}\n\n"
        f"Failing CI output:\n{failure_summary}"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = msg.content[0].text.strip()
        # Strip markdown fences if present
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
        return json.loads(text)
    except json.JSONDecodeError:
        return {"action": "ignore", "summary": f"LLM returned non-JSON: {text[:100]}"}
    except Exception as e:
        return {"action": "ignore", "summary": f"LLM error: {e}"}


async def _llm_describe_conflict(
    anthropic_key: str,
    pr_number: int,
    pr_title: str,
    repo: str,
) -> str:
    """Generate a short WO description for a conflicting PR."""
    if not anthropic_key:
        return f"Resolve merge conflict on PR #{pr_number} ({repo}): {pr_title}"

    system = (
        "You are the intelligence layer of an AI software factory. "
        "Write a concise 2-sentence factory work order description for resolving "
        "a merge conflict on a PR. Be specific about what the agent needs to do: "
        "fetch the branch, rebase onto main, resolve conflicts, force-push."
    )
    user = f"Repository: {repo}\nPR #{pr_number}: {pr_title}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return f"Resolve merge conflict on PR #{pr_number} ({repo}): {pr_title}. Fetch the branch, rebase onto main, resolve any conflicts, and force-push."


# ── Ghost dispatch detection ───────────────────────────────────────────────────

def _find_ghost_entries(dispatch_state: dict, open_branches: set[str]) -> list[str]:
    """
    Return WO IDs whose dispatch entry is claimed/in_progress but appear stale:
    - last_seen is older than GHOST_THRESHOLD_HOURS (or missing)
    - AND the WO branch is no longer open on GitHub
    """
    ghosts = []
    cutoff = datetime.now(UTC) - timedelta(hours=GHOST_THRESHOLD_HOURS)
    for wo_id, entry in dispatch_state.items():
        if entry.get("status") not in ("claimed", "in_progress"):
            continue
        last_seen = entry.get("last_seen") or entry.get("claimed_at")
        if not last_seen:
            ghosts.append(wo_id)
            continue
        try:
            ts = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            if ts < cutoff:
                # Also check: is there an active branch for this WO?
                wo_num = wo_id.replace("WO-", "")
                has_branch = any(wo_num in b for b in open_branches)
                if not has_branch:
                    ghosts.append(wo_id)
        except Exception:
            pass
    return ghosts


# ── Main intelligence pass ─────────────────────────────────────────────────────

async def run_intelligence_pass(
    github_token: str,
    github_repo: str,
    anthropic_key: str,
    dispatch_state: dict,
    enqueue_wo: Callable[[dict], None],
    update_dispatch: Callable[[str, dict], None],
) -> dict:
    """
    Run one intelligence pass. Returns a summary dict logged to /api/intelligence/status.

    Args:
        github_token: GitHub API token
        github_repo:  "owner/repo" string
        anthropic_key: Anthropic API key (may be empty)
        dispatch_state: current _dispatch_state dict (read-only snapshot)
        enqueue_wo: callable(entry_dict) to add a WO to the plan queue
        update_dispatch: callable(wo_id, patch_dict) to update dispatch state
    """
    started_at = datetime.now(UTC).isoformat()
    run_id = uuid.uuid4().hex[:8]
    actions: list[str] = []
    issues_found: list[str] = []

    if not github_token or not github_repo:
        return {"started_at": started_at, "skipped": "No GitHub token/repo configured"}

    async with httpx.AsyncClient(timeout=20) as client:

        # ── 1. Fetch all open PRs ──────────────────────────────────────────────
        try:
            raw_prs = await _gh_get(client, github_token,
                                    f"/repos/{github_repo}/pulls",
                                    {"state": "open", "per_page": 100})
            if not isinstance(raw_prs, list):
                raw_prs = []
        except Exception as e:
            return {"started_at": started_at, "error": f"Could not fetch PRs: {e}"}

        open_branches = {pr["head"]["ref"] for pr in raw_prs}

        for pr in raw_prs:
            pr_num = pr["number"]
            pr_title = pr.get("title", "")
            pr_body = pr.get("body") or ""
            pr_user = pr.get("user", {}).get("login", "")
            pr_sha = pr.get("head", {}).get("sha", "")
            created_at = pr.get("created_at", "")
            is_dependabot = pr_user == "dependabot[bot]"

            # ── 1a. Major-version Dependabot PRs → close ──────────────────────
            if is_dependabot:
                major_pkgs = _parse_major_bumps(pr_body)
                if major_pkgs and not _already_acted("close_major", str(pr_num)):
                    pkg_list = ", ".join(major_pkgs)
                    issues_found.append(f"PR #{pr_num}: major version bump ({pkg_list})")
                    try:
                        await _gh_post(client, github_token,
                                       f"/repos/{github_repo}/issues/{pr_num}/comments",
                                       {"body": f"@dependabot ignore this major version\n\n🤖 **intelligence-loop** · run `{run_id}`"})
                        await _gh_patch(client, github_token,
                                        f"/repos/{github_repo}/pulls/{pr_num}",
                                        {"state": "closed"})
                        _mark_acted("close_major", str(pr_num))
                        actions.append(f"Closed PR #{pr_num} (major version bump: {pkg_list})")
                    except Exception as e:
                        actions.append(f"PR #{pr_num}: failed to close — {e}")
                continue  # skip further checks for Dependabot PRs

            # ── 1b. Fetch individual PR for merge state (requires single fetch) ─
            try:
                pr_detail = await _gh_get(client, github_token,
                                          f"/repos/{github_repo}/pulls/{pr_num}")
                merge_state = pr_detail.get("mergeable_state", "unknown")
            except Exception:
                merge_state = "unknown"

            # ── 1c. Merge conflict PRs → create factory WO ────────────────────
            if merge_state == "dirty" and not _already_acted("conflict_wo", str(pr_num)):
                issues_found.append(f"PR #{pr_num}: merge conflict (DIRTY)")
                wo_desc = await _llm_describe_conflict(anthropic_key, pr_num, pr_title, github_repo)
                wo_id = f"WO-CONF-{pr_num}"
                try:
                    enqueue_wo({
                        "wo": wo_id,
                        "title": f"Resolve conflict: PR #{pr_num} — {pr_title[:60]}",
                        "priority": "P1",
                        "effort": "S",
                        "phase": "backlog",
                        "notes": wo_desc,
                        "pin": False,
                    })
                    await _gh_post(client, github_token,
                                   f"/repos/{github_repo}/issues/{pr_num}/comments",
                                   {"body": (
                                       f"⚠️ **Merge conflict detected** — added to factory queue as `{wo_id}` (P1). "
                                       "An agent will rebase and resolve this shortly.\n\n"
                                       f"🤖 **intelligence-loop** · run `{run_id}`"
                                   )})
                    _mark_acted("conflict_wo", str(pr_num))
                    actions.append(f"Created {wo_id} for PR #{pr_num} merge conflict")
                except Exception as e:
                    actions.append(f"PR #{pr_num}: conflict WO failed — {e}")

            # ── 1d. Long-failing CI → LLM diagnosis ───────────────────────────
            if merge_state not in ("dirty",) and pr_sha and not pr.get("draft"):
                try:
                    checks = await _gh_get(client, github_token,
                                           f"/repos/{github_repo}/commits/{pr_sha}/check-runs",
                                           {"per_page": 50})
                    runs = checks.get("check_runs", []) if isinstance(checks, dict) else []
                    failing_runs = [r for r in runs if r.get("conclusion") == "failure"]
                    if failing_runs and not _already_acted("ci_diagnosis", pr_sha):
                        # Only act if failing for a while (check started_at of oldest failure)
                        oldest_start = min(
                            (r.get("started_at", "") for r in failing_runs),
                            default=""
                        )
                        if oldest_start and _minutes_since(oldest_start) >= FAILURE_THRESHOLD_MINUTES:
                            issues_found.append(
                                f"PR #{pr_num}: CI failing {_minutes_since(oldest_start):.0f}m"
                            )
                            failure_summary = await _get_check_failure_summary(
                                client, github_token, github_repo, pr_sha
                            )
                            diagnosis = await _llm_diagnose_ci_failure(
                                anthropic_key, pr_num, pr_title, failure_summary, github_repo
                            )
                            _mark_acted("ci_diagnosis", pr_sha)

                            diag_action = diagnosis.get("action", "ignore")
                            diag_summary = diagnosis.get("summary", "")

                            if diag_action == "create_wo":
                                wo_id = f"WO-CI-{pr_num}"
                                enqueue_wo({
                                    "wo": wo_id,
                                    "title": diagnosis.get("wo_title", f"Fix CI failure on PR #{pr_num}")[:100],
                                    "priority": diagnosis.get("priority", "P1"),
                                    "effort": "S",
                                    "phase": "backlog",
                                    "notes": diagnosis.get("wo_description", diag_summary),
                                    "pin": diagnosis.get("priority") == "P0",
                                })
                                await _gh_post(client, github_token,
                                               f"/repos/{github_repo}/issues/{pr_num}/comments",
                                               {"body": (
                                                   f"🤖 **CI failure diagnosed** — `{wo_id}` added to factory queue.\n\n"
                                                   f"**Root cause:** {diag_summary}\n\n"
                                                   f"🤖 **intelligence-loop** · run `{run_id}`"
                                               )})
                                actions.append(f"Created {wo_id} for CI failure on PR #{pr_num}: {diag_summary}")

                            elif diag_action == "rerun":
                                # Re-run failed checks via GitHub API
                                for run in failing_runs[:3]:
                                    try:
                                        suite_id = run.get("check_suite", {}).get("id")
                                        if suite_id:
                                            await _gh_post(
                                                client, github_token,
                                                f"/repos/{github_repo}/check-suites/{suite_id}/reattempts",
                                                {},
                                            )
                                    except Exception:
                                        pass
                                actions.append(f"PR #{pr_num}: re-triggered CI ({diag_summary})")

                            else:
                                actions.append(f"PR #{pr_num}: CI ignored ({diag_summary})")

                except Exception as e:
                    pass  # Check run fetch failed — not critical

        # ── 2. Ghost dispatch cleanup ──────────────────────────────────────────
        ghost_ids = _find_ghost_entries(dispatch_state, open_branches)
        for wo_id in ghost_ids:
            entry = dispatch_state.get(wo_id, {})

            if entry.get("ghost_warning"):
                # Already warned — check if >24h with no heartbeat, then escalate
                warned_at_str = entry.get("ghost_warning_at", "")
                try:
                    warned_at = datetime.fromisoformat(warned_at_str)
                    stale_hours = (datetime.now(UTC) - warned_at).total_seconds() / 3600
                    if stale_hours >= GHOST_ESCALATE_HOURS and not _already_acted("ghost_escalate", wo_id):
                        update_dispatch(wo_id, {
                            "status": "ghost",
                            "step": f"auto-cleared — stale >{GHOST_ESCALATE_HOURS}h after ghost_warning · 🤖 intelligence-loop · run `{run_id}`",
                            "last_seen": datetime.now(UTC).isoformat(),
                        })
                        _mark_acted("ghost_escalate", wo_id)
                        actions.append(f"Escalated to ghost: {wo_id} (>24h stale)")
                except Exception:
                    pass
            else:
                # First detection — advisory warning only, do not change status
                if not _already_acted("ghost_warning", wo_id):
                    issues_found.append(f"{wo_id}: ghost dispatch entry (stale, no open branch) — warning set")
                    try:
                        update_dispatch(wo_id, {
                            "ghost_warning": True,
                            "ghost_warning_at": datetime.now(UTC).isoformat(),
                            "step": f"⚠️ ghost warning — no active branch found · 🤖 intelligence-loop · run `{run_id}`",
                        })
                        pr_num = entry.get("pr_number")
                        if pr_num and github_token:
                            await _gh_post(
                                client, github_token,
                                f"/repos/{github_repo}/issues/{pr_num}/comments",
                                {"body": (
                                    f"⚠️ **Ghost warning** — No active branch found for `{wo_id}`. "
                                    f"Human review recommended. If the WO is still in progress, push the branch "
                                    f"or update the heartbeat.\n\n"
                                    f"🤖 **intelligence-loop** · run `{run_id}`"
                                )},
                            )
                        _mark_acted("ghost_warning", wo_id)
                        actions.append(f"Ghost warning set: {wo_id}")
                    except Exception as e:
                        actions.append(f"{wo_id}: ghost warning failed — {e}")

    _flush_acted_on()
    return {
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "issues_found": issues_found,
        "actions_taken": actions,
        "prs_scanned": len(raw_prs),
    }
