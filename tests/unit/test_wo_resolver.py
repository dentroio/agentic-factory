"""Unit tests for scripts/wo_resolver.py (WO-1035, WO-1041)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from wo_resolver import (  # noqa: E402
    branch_name_for,
    extract_wo_from_branch,
    extract_wo_from_title,
    find_claim_path,
    find_spec_path,
    normalize_wo_id,
    parse_wo_number,
    parse_wo_number_from_branch,
    resolve_wo_for_pr,
    wo_number_from_id,
)


def test_normalize_wo_id_collapses_double_prefix():
    assert normalize_wo_id("WO-WO-1035") == "WO-1035"
    assert normalize_wo_id("wo-1035") == "WO-1035"
    assert normalize_wo_id("1035") == "WO-1035"


def test_normalize_wo_id_rejects_invalid():
    with pytest.raises(ValueError):
        normalize_wo_id("")
    with pytest.raises(ValueError):
        normalize_wo_id("WO-abc")


def test_parse_wo_number_from_text():
    assert parse_wo_number("feat(wo-1035): factory resolver") == 1035
    assert parse_wo_number("no wo here") is None


def test_parse_wo_number_from_branch():
    assert parse_wo_number_from_branch("refs/heads/wo/1035-factory-single-wo-resolver") == 1035
    assert parse_wo_number_from_branch("main") is None


def test_wo_number_from_id():
    assert wo_number_from_id("WO-WO-1035") == 1035


def test_find_spec_path_without_zero_padding(tmp_path: Path):
    wo_dir = tmp_path / "work_orders"
    wo_dir.mkdir()
    spec = wo_dir / "WO-1035-factory-single-wo-resolver.md"
    spec.write_text("# WO-1035 — Factory: Single WO Resolver\n", encoding="utf-8")

    found = find_spec_path(1035, wo_dir=wo_dir, repo_root=tmp_path)
    assert found == spec


def test_find_claim_path(tmp_path: Path):
    claim = find_claim_path(1035, repo_root=tmp_path)
    assert claim == tmp_path / "docs/factory/runs/WO-1035.json"


def test_branch_name_for():
    assert branch_name_for(1035, "Factory: Single WO Resolver") == (
        "wo/1035-factory-single-wo-resolver"
    )


# ── WO-1041: resolve_wo_for_pr branch-first precedence ───────────────────────


def test_extract_wo_from_branch_matches():
    assert extract_wo_from_branch("wo/1041-single-wo-resolver") == 1041
    assert extract_wo_from_branch("refs/heads/wo/1041-slug") is None  # not at start
    assert extract_wo_from_branch("main") is None
    assert extract_wo_from_branch("") is None


def test_extract_wo_from_title_matches():
    assert extract_wo_from_title("WO-1041 — Single WO Resolver") == 1041
    assert extract_wo_from_title("fix: WO-410 double close bug") == 410
    assert extract_wo_from_title("no WO here") is None
    assert extract_wo_from_title("") is None


def test_resolve_wo_for_pr_branch_wins_over_title():
    pr = {
        "title": "WO-410 some unrelated title",
        "head": {"ref": "wo/1041-single-wo-resolver"},
    }
    assert resolve_wo_for_pr(pr) == 1041


def test_resolve_wo_for_pr_title_fallback():
    pr = {
        "title": "WO-1041 — Single WO Resolver",
        "head": {"ref": "main"},
    }
    assert resolve_wo_for_pr(pr) == 1041


def test_resolve_wo_for_pr_no_match():
    pr = {"title": "chore: update deps", "head": {"ref": "dependabot/pip/requests"}}
    assert resolve_wo_for_pr(pr) is None


def test_resolve_wo_for_pr_branch_only():
    pr = {"title": "fix: typo", "head": {"ref": "wo/1041-slug"}}
    assert resolve_wo_for_pr(pr) == 1041


def test_resolve_wo_for_pr_title_only():
    pr = {"title": "WO-1041: implement resolver", "head": {"ref": "feature/no-wo"}}
    assert resolve_wo_for_pr(pr) == 1041
