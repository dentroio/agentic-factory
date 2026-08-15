"""Unit tests for scripts/check_risk_tier_approval.py (AF-01)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_risk_tier_approval", REPO_ROOT / "scripts" / "check_risk_tier_approval.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_risk_tier_approval"] = module
    spec.loader.exec_module(module)
    return module


m = _load()


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("wo/440-analyze-coherence", 440),
        ("wo/1-slug", 1),
        ("fix/some-hotfix", None),
        ("dependabot/pip/requests-2.34.2", None),
        ("main", None),
        ("", None),
    ],
)
def test_extract_wo_number(branch, expected):
    assert m.extract_wo_number(branch) == expected


@pytest.mark.parametrize(
    "content,expected",
    [
        ("# WO-1 — Title\n\n**Priority:** P0\n**Effort:** M\n", "P0"),
        ("**Priority:** p2\n", "P2"),
        ("**Priority:** P1 | P2 | P3\n", "P1"),  # template placeholder — first alt wins, deliberately conservative
        ("no priority field here", None),
    ],
)
def test_parse_priority(content, expected, tmp_path):
    f = tmp_path / "WO-1-test.md"
    f.write_text(content)
    assert m.parse_priority(f) == expected


def test_find_spec_checks_both_conventions(tmp_path, monkeypatch):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    monkeypatch.setattr(m, "WO_DIRS", [dir_a, dir_b])

    # Not found anywhere
    assert m.find_spec(99) is None

    # Found only in the second directory
    (dir_b / "WO-99-thing.md").write_text("**Priority:** P2\n")
    assert m.find_spec(99) == dir_b / "WO-99-thing.md"

    # First directory takes precedence when both have it
    (dir_a / "WO-99-thing.md").write_text("**Priority:** P0\n")
    assert m.find_spec(99) == dir_a / "WO-99-thing.md"


def test_has_approval_uses_latest_review_per_reviewer(monkeypatch):
    """A reviewer's later CHANGES_REQUESTED must override an earlier APPROVED,
    and vice versa — only the most recent state per reviewer counts."""
    reviews = [
        {"user": {"login": "alice"}, "state": "APPROVED"},
        {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"},  # supersedes
        {"user": {"login": "bob"}, "state": "COMMENTED"},  # not a review-state, ignored by our filter
    ]
    monkeypatch.setattr(m, "_api_get", lambda url, token: reviews)
    assert m.has_approval("owner/repo", 1, "tok") is False

    reviews.append({"user": {"login": "carol"}, "state": "APPROVED"})
    assert m.has_approval("owner/repo", 1, "tok") is True


def test_main_passes_for_non_wo_branch(monkeypatch):
    monkeypatch.setenv("PR_HEAD_REF", "fix/something")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert m.main() == 0


def test_main_fails_p0_without_approval(monkeypatch, tmp_path):
    wo_dir = tmp_path / "work_orders"
    wo_dir.mkdir()
    (wo_dir / "WO-500-critical.md").write_text("**Priority:** P0\n")
    monkeypatch.setattr(m, "WO_DIRS", [wo_dir])
    monkeypatch.setattr(m, "has_approval", lambda repo, num, token: False)

    monkeypatch.setenv("PR_HEAD_REF", "wo/500-critical")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert m.main() == 1


def test_main_passes_p0_with_approval(monkeypatch, tmp_path):
    wo_dir = tmp_path / "work_orders"
    wo_dir.mkdir()
    (wo_dir / "WO-500-critical.md").write_text("**Priority:** P0\n")
    monkeypatch.setattr(m, "WO_DIRS", [wo_dir])
    monkeypatch.setattr(m, "has_approval", lambda repo, num, token: True)

    monkeypatch.setenv("PR_HEAD_REF", "wo/500-critical")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert m.main() == 0


def test_main_passes_p2_without_approval(monkeypatch, tmp_path):
    wo_dir = tmp_path / "work_orders"
    wo_dir.mkdir()
    (wo_dir / "WO-501-feature.md").write_text("**Priority:** P2\n")
    monkeypatch.setattr(m, "WO_DIRS", [wo_dir])

    monkeypatch.setenv("PR_HEAD_REF", "wo/501-feature")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert m.main() == 0
