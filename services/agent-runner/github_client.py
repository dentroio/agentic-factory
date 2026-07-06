import base64
import os
from pathlib import Path

import httpx

from config import GITHUB_TOKEN, GITHUB_REPO

# When set, WO specs are read from local disk — zero GitHub API calls.
_LOCAL_REPO = os.getenv("LOCAL_REPO_PATH", "")


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def fetch_wo_markdown(wo_number: int, wo_path: str = "docs/project_management/work_orders") -> str:
    """Return the raw markdown for a WO spec, reading from local disk when available."""
    prefix = f"WO-{wo_number}-"

    # Local-first: scan the mounted/cloned repo directory — no API call
    if _LOCAL_REPO:
        wo_dir = Path(_LOCAL_REPO) / wo_path
        if wo_dir.is_dir():
            match = next((f for f in wo_dir.glob(f"{prefix}*.md")), None)
            if match:
                return match.read_text(encoding="utf-8", errors="replace")

    # Fallback: GitHub API
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{wo_path}",
                headers=_headers(),
            )
            resp.raise_for_status()
            files = resp.json()
            file_match = next((f for f in files if f["name"].startswith(prefix)), None)
            if not file_match:
                return f"[WO-{wo_number} spec not found in {wo_path}]"
            data_resp = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_match['path']}",
                headers=_headers(),
            )
            data_resp.raise_for_status()
            return base64.b64decode(data_resp.json()["content"]).decode("utf-8")
    except Exception as e:
        return f"[WO-{wo_number} spec unavailable: {e}]"
