import base64

import httpx

from config import GITHUB_TOKEN, GITHUB_REPO


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def fetch_wo_markdown(wo_number: int, wo_path: str = "docs/project_management/work_orders") -> str:
    """Fetch the raw markdown for a WO spec from GitHub."""
    prefix = f"WO-{wo_number}-"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{wo_path}",
            headers=_headers(),
        )
        resp.raise_for_status()
        files = resp.json()
        match = next((f for f in files if f["name"].startswith(prefix)), None)
        if not match:
            return f"[WO-{wo_number} spec not found in {wo_path}]"
        data_resp = await client.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{match['path']}",
            headers=_headers(),
        )
        data_resp.raise_for_status()
        return base64.b64decode(data_resp.json()["content"]).decode("utf-8")
