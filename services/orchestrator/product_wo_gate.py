"""Product WO eligibility — keep the Clarion factory on Clarion specs only.

The orchestrator queue has no repo column. Without a gate, engine WOs
(dentroio/agentic-factory docs/work_orders) can be enqueued and claimed against
the product worktree (GITHUB_REPO / LOCAL_REPO_MOUNT).
"""
from __future__ import annotations

import re
from pathlib import Path


def normalize_wo_id(wo: str) -> str:
    wo_id = (wo or "").strip()
    wo_upper = wo_id.upper()
    if not wo_upper.startswith("WO-"):
        wo_id = f"WO-{wo_id}"
    else:
        wo_id = wo_upper
    while wo_id.startswith("WO-WO-"):
        wo_id = "WO-" + wo_id[6:]
    return wo_id


def wo_number(wo_id: str) -> int | None:
    m = re.search(r"(\d+)$", normalize_wo_id(wo_id))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def product_spec_on_disk(local_repo: str, wo_path: str, wo_id: str) -> bool:
    """True when LOCAL_REPO_MOUNT/wo_path contains WO-{n}-*.md."""
    num = wo_number(wo_id)
    if num is None or not local_repo:
        return False
    wo_dir = Path(local_repo) / wo_path
    if not wo_dir.is_dir():
        return False
    return any(wo_dir.glob(f"WO-{num}-*.md"))


def product_spec_in_cache(
    specs_cache: dict[int, dict] | None,
    github_repo: str,
    wo_id: str,
) -> bool:
    """True when the primary specs cache has this number for github_repo."""
    num = wo_number(wo_id)
    if num is None or not specs_cache:
        return False
    spec = specs_cache.get(num) or {}
    if not spec:
        return False
    spec_repo = (spec.get("repo") or github_repo or "").strip()
    return spec_repo == (github_repo or "").strip()


def product_has_spec(
    wo_id: str,
    *,
    local_repo: str = "",
    wo_path: str = "docs/project_management/work_orders",
    github_repo: str = "",
    specs_cache: dict[int, dict] | None = None,
) -> bool:
    """Eligible for this factory's queue/claim when a product spec is present."""
    wo_id = normalize_wo_id(wo_id)
    if product_spec_on_disk(local_repo, wo_path, wo_id):
        return True
    return product_spec_in_cache(specs_cache, github_repo, wo_id)
