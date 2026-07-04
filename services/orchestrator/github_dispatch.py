"""Trigger GitHub Actions workflow_dispatch for cloud Codex agent runs."""
import os

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
CODEX_WORKFLOW_FILE = os.getenv("CODEX_WORKFLOW_FILE", "codex-dispatch.yml")


def _headers() -> dict:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def trigger_codex_workflow(
    repo: str,
    wo_id: str,
    slug: str = "codex-run",
    ref: str = "main",
) -> bool:
    """POST a workflow_dispatch event to run Codex on the target repo.

    Returns True on HTTP 204 (accepted), False on any error.
    """
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{CODEX_WORKFLOW_FILE}/dispatches"
    payload = {
        "ref": ref,
        "inputs": {"wo_id": wo_id, "wo_slug": slug},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            if resp.status_code == 204:
                return True
            print(f"[dispatch] workflow_dispatch {wo_id} → HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[dispatch] workflow_dispatch failed for {wo_id}: {e}")
        return False
