"""Unit tests for product_wo_gate — Clarion-only queue eligibility."""
from __future__ import annotations

import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "services" / "orchestrator"
sys.path.insert(0, str(ORCH))

from product_wo_gate import (  # noqa: E402
    normalize_wo_id,
    product_has_spec,
    product_spec_in_cache,
    product_spec_on_disk,
    wo_number,
)


def test_normalize_wo_id():
    assert normalize_wo_id("564") == "WO-564"
    assert normalize_wo_id("wo-564") == "WO-564"
    assert normalize_wo_id("WO-WO-564") == "WO-564"


def test_wo_number():
    assert wo_number("WO-1096") == 1096
    assert wo_number("bad") is None


def test_product_spec_on_disk(tmp_path: Path):
    wo_dir = tmp_path / "docs" / "project_management" / "work_orders"
    wo_dir.mkdir(parents=True)
    (wo_dir / "WO-562-hover.md").write_text("# WO-562\n", encoding="utf-8")
    assert product_spec_on_disk(
        str(tmp_path), "docs/project_management/work_orders", "WO-562"
    )
    assert not product_spec_on_disk(
        str(tmp_path), "docs/project_management/work_orders", "WO-1096"
    )


def test_product_spec_in_cache_requires_matching_repo():
    cache = {562: {"title": "hover", "repo": "dentroio/clarion"}}
    assert product_spec_in_cache(cache, "dentroio/clarion", "WO-562")
    assert not product_spec_in_cache(cache, "dentroio/clarion", "WO-1096")
    engine = {1096: {"title": "guide", "repo": "dentroio/agentic-factory"}}
    assert not product_spec_in_cache(engine, "dentroio/clarion", "WO-1096")


def test_product_has_spec_prefers_disk(tmp_path: Path):
    wo_dir = tmp_path / "docs" / "project_management" / "work_orders"
    wo_dir.mkdir(parents=True)
    (wo_dir / "WO-562-hover.md").write_text("# WO-562\n", encoding="utf-8")
    assert product_has_spec(
        "WO-562",
        local_repo=str(tmp_path),
        wo_path="docs/project_management/work_orders",
        github_repo="dentroio/clarion",
        specs_cache={},
    )
    assert not product_has_spec(
        "WO-1096",
        local_repo=str(tmp_path),
        wo_path="docs/project_management/work_orders",
        github_repo="dentroio/clarion",
        specs_cache={1096: {"title": "x", "repo": "dentroio/agentic-factory"}},
    )
