"""`make ci-local` must exist, and must run what GitHub Actions runs.

"The CI gate is the contract" appears in README.md, ENGINEER.md and
AGENT_PROCESS.md; `make ci-local` is named in all of them, in CLAUDE.md, in
AGENTS.md, in the Cursor rules, and in the WO template's pre-PR checklist.
services/agent-runner/quality_gate.py runs it as a real subprocess against
every agent's worktree. It was never added to this repo's Makefile — it lived
only in Makefile.template — so every agent told to run the gate before opening
a PR got "No rule to make target 'ci-local'".

Two failure modes to hold shut. The target disappearing again, and the slower
one: ci.yml growing a step that ci-local doesn't have, so the local gate passes
and CI fails anyway. ENGINEER.md already asks a human to check for that
by hand on every change; this checks it on every run.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _make_targets() -> set[str]:
    return set(re.findall(r"^([a-zA-Z][\w-]*):", MAKEFILE.read_text(), re.MULTILINE))


def _recipe(target: str) -> str:
    """Return the recipe lines (tab-indented) for a target."""
    lines = MAKEFILE.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(target)}:", ln))
    body = []
    for ln in lines[start + 1:]:
        if ln.startswith("\t"):
            body.append(ln.lstrip("\t"))
        elif ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        else:
            break
    return "\n".join(body)


def _normalize(cmd: str) -> str:
    """Compare intent, not shell dialect.

    The Makefile has to escape `$` and reaches the interpreter through
    $(PYTHON); the workflow runs `python` directly under setup-python.
    """
    cmd = cmd.replace("$$", "$").replace("$(PYTHON)", "python").replace("python3", "python")
    cmd = re.sub(r"\bpython -m pytest\b", "pytest", cmd)
    return " ".join(cmd.split())


def _pytest_invocation(text: str, source: str) -> str:
    """The line that actually runs the suite.

    Matched on the test path rather than the word "pytest" — otherwise this
    picks up ci.yml's `pip install pytest ...` or the Makefile's
    `import pytest` availability guard.
    """
    for line in text.splitlines():
        if "pytest tests/" in line:
            return line.strip()
    raise AssertionError(f"no pytest invocation found in {source}")


def test_ci_local_exists():
    assert MAKEFILE.exists()
    assert "ci-local" in _make_targets(), (
        "make ci-local is mandated by AGENT_PROCESS.md, README.md, CLAUDE.md, AGENTS.md, "
        "the Cursor rules and quality_gate.py — it must exist in the Makefile"
    )


def test_ci_local_composes_targets_that_exist():
    targets = _make_targets()
    called = re.findall(r"\$\(MAKE\)\s+([\w-]+)", _recipe("ci-local"))

    assert called, "ci-local runs nothing"
    missing = [t for t in called if t not in targets]
    assert missing == [], f"ci-local calls undefined target(s): {missing}"


def test_ci_local_runs_the_unit_tests_and_the_pre_pr_check():
    called = re.findall(r"\$\(MAKE\)\s+([\w-]+)", _recipe("ci-local"))

    assert "test" in called
    assert "pre-pr-check" in called
    assert "secrets" in called


def test_ci_has_gitleaks_job_and_local_secrets_target():
    ci = CI_WORKFLOW.read_text()
    assert "name: Secret Detection (Gitleaks)" in ci
    assert "gitleaks/gitleaks-action@" in ci
    recipe = _recipe("secrets")
    assert "gitleaks detect" in recipe
    assert "|| true" not in recipe


def test_make_test_matches_the_pytest_invocation_in_ci():
    """The drift guard. If ci.yml changes how it runs pytest — a different
    path, added flags, a different exit-code tolerance — this fails until the
    Makefile is updated to match."""
    ci = _normalize(_pytest_invocation(CI_WORKFLOW.read_text(), "ci.yml"))
    local = _normalize(_pytest_invocation(_recipe("test"), "the Makefile's test target"))

    assert local == ci, f"make test does not mirror ci.yml\n  ci.yml: {ci}\n  Makefile: {local}"


def test_pre_pr_check_target_points_at_the_real_script():
    assert "scripts/pre_pr_check.py" in _recipe("pre-pr-check")
    assert (ROOT / "scripts" / "pre_pr_check.py").exists()


def test_the_gate_has_no_failure_bypasses():
    """`|| true` in the gate is the one thing every doc says it must not have.

    Pytest exit 5 (no tests collected) must fail the gate. An empty or
    renamed tests/unit/ is not a pass.
    """
    for target in ("ci-local", "test", "pre-pr-check", "secrets"):
        recipe = _recipe(target)
        assert "|| true" not in recipe, f"{target} swallows failures with || true"
        for match in re.findall(r"\|\|\s*\{([^}]*)\}", recipe):
            assert "exit" in match, f"{target} has a || branch that never exits: {match}"
            assert "eq 5" not in match, f"{target} still treats an empty suite as green: {match}"


def test_ci_does_not_treat_an_empty_suite_as_green():
    ci = CI_WORKFLOW.read_text()
    makefile_test = _recipe("test")
    assert "eq 5" not in ci
    assert "eq 5" not in makefile_test
    assert "-ge 20" in ci
    assert "-ge 20" in makefile_test
