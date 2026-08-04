"""Parity test for the three independent copies of resolve_wo_for_pr /
resolve_all_wos_for_pr (WO-1035/1041 lineage; F-01 audit follow-up).

scripts/wo_resolver.py, services/orchestrator/wo_resolver.py, and
services/status-site/wo_parser.py each implement PR->WO resolution
separately — orchestrator and status-site are deployed as separate Docker
images with narrow build contexts (neither can COPY a shared module from
outside its own service directory without pulling in the whole repo,
including .git), so a single shared file isn't a safe option here.

This test is the substitute: it loads all three copies directly from disk
by file path (not by package import, since two of the three files are both
literally named "wo_resolver.py" and would collide under a normal import)
and asserts they agree on the same battery of PR-title/branch cases. If
someone fixes a bug or adds a case in one copy and forgets the other two,
this fails CI instead of the drift silently shipping — which is exactly how
orchestrator's copy ended up missing resolve_all_wos_for_pr entirely until
this was noticed by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scripts_resolver = _load("scripts_wo_resolver", REPO_ROOT / "scripts" / "wo_resolver.py")
orchestrator_resolver = _load(
    "orchestrator_wo_resolver", REPO_ROOT / "services" / "orchestrator" / "wo_resolver.py"
)
status_site_parser = _load(
    "status_site_wo_parser", REPO_ROOT / "services" / "status-site" / "wo_parser.py"
)

IMPLEMENTATIONS = [
    ("scripts/wo_resolver.py", scripts_resolver),
    ("services/orchestrator/wo_resolver.py", orchestrator_resolver),
    ("services/status-site/wo_parser.py", status_site_parser),
]

# (description, pr_dict) — covers the cases that matter: branch-only,
# title-only, branch+title agreeing, no match, and the multi-WO title that
# originally exposed the orchestrator/status-site drift.
PR_CASES = [
    ("branch only", {"head": {"ref": "wo/1035-canonical-entity-uuid"}, "title": "some PR"}),
    ("title only, no branch match", {"head": {"ref": "feature/misc"}, "title": "WO-417: Coverage Consolidation"}),
    (
        "branch takes precedence over a different title number",
        {"head": {"ref": "wo/1035-slug"}, "title": "WO-999: unrelated title"},
    ),
    ("no WO anywhere", {"head": {"ref": "chore/bump-deps"}, "title": "Bump requests to 2.34"}),
    (
        "conflict-resolution PR naming two WOs",
        {
            "head": {"ref": "wo/1035-resolve-conflict"},
            "title": "WO-1035: Resolve conflict: PR #455 — WO-417: Coverage Consolidation",
        },
    ),
    (
        "two WOs in title, neither in branch",
        {"head": {"ref": "chore/misc"}, "title": "WO-201 / WO-202: shared migration"},
    ),
    ("empty PR dict", {}),
    ("missing head entirely", {"title": "WO-88: no head key"}),
]


@pytest.mark.parametrize("description,pr", PR_CASES)
def test_resolve_wo_for_pr_agrees_across_all_three(description, pr):
    results = {name: impl.resolve_wo_for_pr(pr) for name, impl in IMPLEMENTATIONS}
    values = set(results.values())
    assert len(values) == 1, (
        f"resolve_wo_for_pr disagrees on case {description!r}: {results}"
    )


@pytest.mark.parametrize("description,pr", PR_CASES)
def test_resolve_all_wos_for_pr_agrees_across_all_three(description, pr):
    results = {name: impl.resolve_all_wos_for_pr(pr) for name, impl in IMPLEMENTATIONS}
    values = {tuple(v) for v in results.values()}
    assert len(values) == 1, (
        f"resolve_all_wos_for_pr disagrees on case {description!r}: {results}"
    )


def test_multi_wo_case_actually_returns_both():
    # Not just parity — pin the actual expected behavior so a future "fix"
    # that makes all three agree on the WRONG answer still fails.
    pr = {
        "head": {"ref": "wo/1035-resolve-conflict"},
        "title": "WO-1035: Resolve conflict: PR #455 — WO-417: Coverage Consolidation",
    }
    for name, impl in IMPLEMENTATIONS:
        assert impl.resolve_all_wos_for_pr(pr) == [417, 1035], f"{name} returned wrong set"
