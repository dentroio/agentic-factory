"""WO creation and editing — writes directly to the locally-mounted repo.

When LOCAL_REPO_MOUNT is set (normal local development), all writes go to disk
immediately. The factory reads from the same mount, so new WOs are visible
instantly without any GitHub API roundtrip or PR merge delay.

Falls back to GitHub API only when LOCAL_REPO_MOUNT is not set (remote/cloud
deployment where no local mount is available).
"""
import base64
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")
PLAN_PATH = os.getenv("PLAN_PATH", "docs/factory/PLAN.json")
LOCAL_REPO_MOUNT = os.getenv("LOCAL_REPO_MOUNT", "")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8100")


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
    """Return max existing WO number + 1. Reads from local mount when available."""
    if LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / wo_path
        if wo_dir.is_dir():
            numbers = [
                int(m.group(1))
                for path in wo_dir.glob("WO-*.md")
                if (m := re.match(r"WO-(\d+)", path.name))
            ]
            return max(numbers, default=374) + 1

    # Fallback: GitHub API (remote deployment without a local mount)
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


def _write_wo_local(wo_data: dict, wo_path: str, plan_path: str) -> dict:
    """Write WO spec to the local repo mount + register in the orchestrator queue DB."""
    number = wo_data["number"]
    title = wo_data["title"]
    slug = _slugify(title)

    spec_path = Path(LOCAL_REPO_MOUNT) / wo_path / f"WO-{number}-{slug}.md"
    spec_path.write_text(render_wo_template(wo_data), encoding="utf-8")

    return {
        "url": f"https://github.com/{GITHUB_REPO}/blob/main/{wo_path}/WO-{number}-{slug}.md",
        "wo_number": number,
        "local_path": str(spec_path),
    }


def _parse_docs_required(markdown: str) -> list[dict]:
    """Extract Documentation Required checklist items from a WO spec."""
    import re as _re
    m = _re.search(
        r"^## Documentation Required\s*\n(.*?)(?=\n^##|\Z)",
        markdown, _re.MULTILINE | _re.DOTALL,
    )
    if not m:
        return []
    items = []
    for line in m.group(1).splitlines():
        clean = line.strip().lstrip("-").lstrip("[ ]").lstrip("- [ ]").strip()
        if clean:
            items.append({"item": clean, "completed": False})
    return items


async def _register_in_queue(wo_data: dict) -> None:
    """Add the new WO to the orchestrator queue DB via API.

    Parses the rendered WO spec for a '## Documentation Required' section and
    stores those items in docs_required so the documentation reviewer can enforce them.
    """
    import json as _json
    number = wo_data["number"]
    title = wo_data["title"]

    # Parse docs_required from the rendered spec markdown
    spec_md = render_wo_template(wo_data)
    docs_required_items = _parse_docs_required(spec_md)

    payload = {
        "wo": f"WO-{number}",
        "title": title,
        "phase": wo_data.get("phase", ""),
        "priority": wo_data.get("priority", "P2"),
        "effort": wo_data.get("effort", ""),
        "pin": False,
        "blocks_milestones": wo_data.get("blocks_milestones", []),
        "depends_on": wo_data.get("depends_on", []),
        "notes": wo_data.get("notes", ""),
        "docs_required": _json.dumps(docs_required_items),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/queue", json=payload)
            resp.raise_for_status()
    except Exception as e:
        print(f"[github_writer] queue registration for WO-{number} failed: {e}")


async def create_wo(
    wo_data: dict, token: str, repo: str, wo_path: str, plan_path: str
) -> dict:
    """Create a WO spec + register in the orchestrator queue DB.

    Writes directly to the local repo mount when available — the factory
    sees it immediately, no GitHub roundtrip needed. Falls back to GitHub
    API for remote deployments. In both cases, the queue DB is updated via
    the orchestrator API instead of writing to PLAN.json.
    """
    if LOCAL_REPO_MOUNT:
        result = _write_wo_local(wo_data, wo_path, plan_path)
        await _register_in_queue(wo_data)
        return result

    # Fallback: commit directly to remote main via GitHub API
    number = wo_data["number"]
    title = wo_data["title"]
    slug = _slugify(title)
    spec_path = f"{wo_path}/WO-{number}-{slug}.md"
    spec_md = render_wo_template(wo_data)

    async with httpx.AsyncClient(timeout=25) as client:
        await _put(client, f"/repos/{repo}/contents/{spec_path}", token, {
            "message": f"docs(pm): WO-{number} — {title}",
            "content": base64.b64encode(spec_md.encode()).decode(),
            "branch": "main",
        })

    await _register_in_queue(wo_data)

    wo_url = f"https://github.com/{repo}/blob/main/{spec_path}"
    return {"url": wo_url, "wo_number": number}


async def read_wo_file(wo_id: str, token: str, repo: str, wo_path: str) -> tuple[str, str]:
    """Return (raw_content, file_path) for the given WO ID."""
    if LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / wo_path
        match = next((p for p in wo_dir.glob(f"{wo_id}-*.md")), None)
        if not match:
            raise ValueError(f"No spec file found for {wo_id}")
        return match.read_text(encoding="utf-8"), str(match.relative_to(LOCAL_REPO_MOUNT))

    async with httpx.AsyncClient(timeout=15) as client:
        items = await _get(client, f"/repos/{repo}/contents/{wo_path}", token)
        if not isinstance(items, list):
            raise ValueError("Could not list WO files")
        match = next(
            (f for f in items if isinstance(f, dict) and f.get("name", "").startswith(f"{wo_id}-")),
            None,
        )
        if not match:
            raise ValueError(f"No spec file found for {wo_id}")
        raw = await httpx.AsyncClient(timeout=15).get(
            f"https://api.github.com/repos/{repo}/contents/{match['path']}",
            headers=_headers(token),
        )
        raw.raise_for_status()
        data = raw.json()
        content = base64.b64decode(data["content"]).decode()
        return content, match["path"]


async def edit_wo(wo_id: str, new_content: str, token: str, repo: str, wo_path: str) -> dict:
    """Update an existing WO spec file.

    Writes directly to local mount when available (instant, no PR).
    Falls back to GitHub branch + PR for remote deployments.
    """
    if LOCAL_REPO_MOUNT:
        wo_dir = Path(LOCAL_REPO_MOUNT) / wo_path
        match = next((p for p in wo_dir.glob(f"{wo_id}-*.md")), None)
        if not match:
            raise ValueError(f"No spec file found for {wo_id}")
        match.write_text(new_content, encoding="utf-8")
        return {"local": True, "path": str(match)}

    # Fallback: create branch + PR for remote deployment
    number = wo_id.replace("WO-", "").lstrip("0") or "0"
    branch = f"factory/edit-wo-{number}"

    async with httpx.AsyncClient(timeout=25) as client:
        items = await _get(client, f"/repos/{repo}/contents/{wo_path}", token)
        if not isinstance(items, list):
            raise ValueError("Could not list WO files")
        match = next(
            (f for f in items if isinstance(f, dict) and f.get("name", "").startswith(f"{wo_id}-")),
            None,
        )
        if not match:
            raise ValueError(f"No spec file found for {wo_id}")

        ref = await _get(client, f"/repos/{repo}/git/ref/heads/main", token)
        base_sha = ref["object"]["sha"]
        try:
            await _post(client, f"/repos/{repo}/git/refs", token, {
                "ref": f"refs/heads/{branch}",
                "sha": base_sha,
            })
        except Exception:
            pass  # branch already exists — reuse it

        await _put(client, f"/repos/{repo}/contents/{match['path']}", token, {
            "message": f"docs(pm): update {wo_id} spec",
            "content": base64.b64encode(new_content.encode()).decode(),
            "sha": match["sha"],
            "branch": branch,
        })

        pr = await _post(client, f"/repos/{repo}/pulls", token, {
            "title": f"docs(pm): update {wo_id} spec",
            "body": "Updated via AI Factory Plan Authoring UI.",
            "head": branch,
            "base": "main",
        })
        return {"pr_url": pr["html_url"]}


async def add_phase(
    phase_data: dict, token: str, repo: str, plan_path: str
) -> dict:
    """Add a phase to the orchestrator queue DB."""
    phase_id = phase_data["id"]
    payload = {
        "id": phase_id,
        "label": phase_data.get("label", phase_id),
        "target_date": phase_data.get("target_date", ""),
        "milestone_id": phase_data.get("milestone_id") or phase_data.get("milestone") or None,
        "parallel": bool(phase_data.get("parallel", False)),
        "description": phase_data.get("description", ""),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{ORCHESTRATOR_URL}/api/phases", json=payload)
        if resp.status_code == 409:
            return {"error": f"Phase '{phase_id}' already exists"}
        resp.raise_for_status()
    return {"ok": True, "phase_id": phase_id}


async def add_milestone(
    milestone_data: dict, token: str, repo: str, plan_path: str
) -> dict:
    """Add a milestone to the orchestrator queue DB."""
    milestone_id = milestone_data["id"]
    payload = {
        "id": milestone_id,
        "label": milestone_data.get("label", milestone_id),
        "target_date": milestone_data.get("target_date", ""),
        "description": milestone_data.get("description", ""),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{ORCHESTRATOR_URL}/api/milestones", json=payload)
        if resp.status_code == 409:
            return {"error": f"Milestone '{milestone_id}' already exists"}
        resp.raise_for_status()
    return {"ok": True, "milestone_id": milestone_id}
