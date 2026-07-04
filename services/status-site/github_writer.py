"""GitHub API write-back — create WO specs, update PLAN.json, open PRs."""
import base64
import json
import os
import re
from datetime import UTC, datetime

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
PLAN_PATH = os.getenv("PLAN_PATH", "docs/factory/PLAN.json")


def _headers(token: str) -> dict:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _get(client: httpx.AsyncClient, path: str, token: str) -> dict | list:
    resp = await client.get(f"https://api.github.com{path}", headers=_headers(token))
    resp.raise_for_status()
    return resp.json()


async def _post(client: httpx.AsyncClient, path: str, token: str, body: dict) -> dict:
    resp = await client.post(f"https://api.github.com{path}", headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json()


async def _put(client: httpx.AsyncClient, path: str, token: str, body: dict) -> dict:
    resp = await client.put(f"https://api.github.com{path}", headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json()


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", title.lower())
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug[:50].rstrip("-")


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def render_wo_template(wo_data: dict) -> str:
    number = wo_data["number"]
    title = wo_data["title"]
    priority = wo_data.get("priority", "P2")
    effort = wo_data.get("effort", "M")
    services = wo_data.get("services", "none")
    depends_on = wo_data.get("depends_on", [])
    notes = wo_data.get("notes", "")
    problem = wo_data.get("problem", "")
    what_to_build = wo_data.get("what_to_build", "")
    criteria = wo_data.get("acceptance_criteria", [])

    depends_str = ", ".join(depends_on) if depends_on else "none"
    slug = _slugify(title)

    criteria_rows = "\n".join(f"| {i} | {c} |" for i, c in enumerate(criteria, 1))
    criteria_table = f"| # | Criterion |\n|---|-----------|\n{criteria_rows}" if criteria_rows else "| # | Criterion |\n|---|-----------|"

    return f"""# WO-{number} — {title}

**Status:** 📋 Open
**Priority:** {priority}
**Effort:** {effort}
**Services:** {services}
**Depends on:** {depends_str}

---

## Problem

{problem}

---

## What to Build

{what_to_build}

---

## Quality & Security Requirements

- [ ] `make ci-local` passes clean
- [ ] No hardcoded secrets or credentials
- [ ] All user inputs validated at system boundaries
- [ ] New API endpoints use `require_role()` dependency
- [ ] Security scanner: no CRITICAL or HIGH findings

---

## Acceptance Criteria

{criteria_table}

---

## Execution

- **Branch:** `wo/{number}-{slug}`
- **Priority:** {priority}
- **Notes:** {notes or "—"}
"""


async def next_wo_number(repo: str, wo_path: str, token: str) -> int:
    """Return max existing WO number + 1."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            items = await _get(client, f"/repos/{repo}/contents/{wo_path}", token)
            if not isinstance(items, list):
                return 374
            numbers = [
                int(m.group(1))
                for item in items
                if item.get("type") == "file" and (m := re.match(r"WO-(\d+)", item["name"]))
            ]
            return max(numbers, default=350) + 1
        except Exception:
            return 374


async def create_wo(
    wo_data: dict, token: str, repo: str, wo_path: str, plan_path: str
) -> dict:
    """Create WO spec + update PLAN.json + open PR. Returns {pr_url, wo_number, branch}."""
    number = wo_data["number"]
    title = wo_data["title"]
    slug = _slugify(title)
    spec_path = f"{wo_path}/WO-{number}-{slug}.md"
    branch = f"factory/wo-{number}-spec"

    spec_md = render_wo_template(wo_data)

    async with httpx.AsyncClient(timeout=25) as client:
        ref = await _get(client, f"/repos/{repo}/git/ref/heads/main", token)
        base_sha = ref["object"]["sha"]

        await _post(client, f"/repos/{repo}/git/refs", token, {
            "ref": f"refs/heads/{branch}",
            "sha": base_sha,
        })

        await _put(client, f"/repos/{repo}/contents/{spec_path}", token, {
            "message": f"docs(pm): WO-{number} — {title}",
            "content": base64.b64encode(spec_md.encode()).decode(),
            "branch": branch,
        })

        plan_file = await _get(client, f"/repos/{repo}/contents/{plan_path}", token)
        plan = json.loads(base64.b64decode(plan_file["content"]).decode())  # type: ignore[arg-type]

        plan.setdefault("queue", []).append({
            "wo": f"WO-{number}",
            "title": title,
            "phase": wo_data.get("phase", "p2"),
            "priority": wo_data.get("priority", "P2"),
            "effort": wo_data.get("effort", "M"),
            "blocks_milestones": wo_data.get("blocks_milestones", []),
            "depends_on": wo_data.get("depends_on", []),
            "status": "open",
            "pin": False,
            "notes": wo_data.get("notes", ""),
        })
        plan["last_updated"] = _today()

        await _put(client, f"/repos/{repo}/contents/{plan_path}", token, {
            "message": f"docs(pm): add WO-{number} to PLAN.json queue",
            "content": base64.b64encode(json.dumps(plan, indent=2).encode()).decode(),
            "sha": plan_file["sha"],  # type: ignore[index]
            "branch": branch,
        })

        pr = await _post(client, f"/repos/{repo}/pulls", token, {
            "title": f"docs(pm): WO-{number} — {title}",
            "body": (
                f"Created via AI Factory Plan Authoring UI.\n\n"
                f"- `WO-{number}-{slug}.md` spec file added\n"
                f"- PLAN.json queue entry added\n\n"
                f"Review and merge to make this WO visible to the orchestrator."
            ),
            "head": branch,
            "base": "main",
        })

        return {"pr_url": pr["html_url"], "wo_number": number, "branch": branch}


async def add_phase(
    phase_data: dict, token: str, repo: str, plan_path: str
) -> dict:
    """Add a phase to PLAN.json and open a PR."""
    phase_id = phase_data["id"]
    branch = f"factory/phase-{phase_id}"

    async with httpx.AsyncClient(timeout=25) as client:
        ref = await _get(client, f"/repos/{repo}/git/ref/heads/main", token)
        base_sha = ref["object"]["sha"]

        await _post(client, f"/repos/{repo}/git/refs", token, {
            "ref": f"refs/heads/{branch}",
            "sha": base_sha,
        })

        plan_file = await _get(client, f"/repos/{repo}/contents/{plan_path}", token)
        plan = json.loads(base64.b64decode(plan_file["content"]).decode())  # type: ignore[arg-type]

        if any(p["id"] == phase_id for p in plan.get("phases", [])):
            return {"error": f"Phase '{phase_id}' already exists"}

        plan.setdefault("phases", []).append({
            "id": phase_id,
            "label": phase_data.get("label", phase_id),
            "target_date": phase_data.get("target_date", ""),
            "milestone": phase_data.get("milestone") or None,
            "description": phase_data.get("description", ""),
            "parallel": bool(phase_data.get("parallel", False)),
        })
        plan["last_updated"] = _today()

        await _put(client, f"/repos/{repo}/contents/{plan_path}", token, {
            "message": f"docs(pm): add phase '{phase_id}'",
            "content": base64.b64encode(json.dumps(plan, indent=2).encode()).decode(),
            "sha": plan_file["sha"],  # type: ignore[index]
            "branch": branch,
        })

        pr = await _post(client, f"/repos/{repo}/pulls", token, {
            "title": f"docs(pm): add phase '{phase_id}' to PLAN.json",
            "body": f"Created via AI Factory Plan Authoring UI.\n\nAdds phase: **{phase_data.get('label', phase_id)}**",
            "head": branch,
            "base": "main",
        })
        return {"pr_url": pr["html_url"]}


async def add_milestone(
    milestone_data: dict, token: str, repo: str, plan_path: str
) -> dict:
    """Add a milestone to PLAN.json and open a PR."""
    milestone_id = milestone_data["id"]
    branch = f"factory/milestone-{milestone_id}"

    async with httpx.AsyncClient(timeout=25) as client:
        ref = await _get(client, f"/repos/{repo}/git/ref/heads/main", token)
        base_sha = ref["object"]["sha"]

        await _post(client, f"/repos/{repo}/git/refs", token, {
            "ref": f"refs/heads/{branch}",
            "sha": base_sha,
        })

        plan_file = await _get(client, f"/repos/{repo}/contents/{plan_path}", token)
        plan = json.loads(base64.b64decode(plan_file["content"]).decode())  # type: ignore[arg-type]

        if any(m["id"] == milestone_id for m in plan.get("milestones", [])):
            return {"error": f"Milestone '{milestone_id}' already exists"}

        plan.setdefault("milestones", []).append({
            "id": milestone_id,
            "label": milestone_data.get("label", milestone_id),
            "target_date": milestone_data.get("target_date", ""),
            "description": milestone_data.get("description", ""),
        })
        plan["last_updated"] = _today()

        await _put(client, f"/repos/{repo}/contents/{plan_path}", token, {
            "message": f"docs(pm): add milestone '{milestone_id}'",
            "content": base64.b64encode(json.dumps(plan, indent=2).encode()).decode(),
            "sha": plan_file["sha"],  # type: ignore[index]
            "branch": branch,
        })

        pr = await _post(client, f"/repos/{repo}/pulls", token, {
            "title": f"docs(pm): add milestone '{milestone_id}' to PLAN.json",
            "body": f"Created via AI Factory Plan Authoring UI.\n\nAdds milestone: **{milestone_data.get('label', milestone_id)}**",
            "head": branch,
            "base": "main",
        })
        return {"pr_url": pr["html_url"]}
