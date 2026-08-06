"""The AI review gate must never be green without a verdict behind it.

ai-review.yml used to short-circuit on the HEAD commit message — auto-generated
commits and GitHub's "Update branch" merge commits set `skip=true`, every
reviewing step was conditioned on `skip != 'true'`, and the only step that
could fail the job was conditioned on the reviewer's outcome. Skip therefore
meant pass: a required check reporting success with nothing behind it. (It was
also dead code — on a pull_request event `git log -1` reads GitHub's synthetic
refs/pull/N/merge commit, which matches none of those patterns — so it opened
the hole without ever delivering the token saving it was there for.)

The same shape appeared a second way: the diff was filtered through an
allow-list of source extensions, so a PR touching only Dockerfiles, .hcl, JSON
or .js produced an empty diff, skipped the reviewer, and went green.

Both are the one mistake — the gate failing open instead of blocking. These
tests hold the corrected shape in place: the verdict step runs no matter what
happened before it, denies by default, and nothing upstream can quietly route
around it.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ai-review.yml"

VERDICT_STEP = "Enforce the review verdict"


def _text() -> str:
    return WORKFLOW.read_text()


def _steps() -> list[str]:
    """The workflow's steps, one string each, comments and all."""
    body = _text().split("\n    steps:\n", 1)[1]
    return [s for s in re.split(r"\n(?=      - )", body) if s.strip()]


def _step(name: str) -> str:
    for step in _steps():
        if f"name: {name}" in step:
            return step
    raise AssertionError(f"ai-review.yml has no step named {name!r}")


def _run_script(step: str) -> str:
    """The shell body of a step's `run: |` block."""
    lines = step.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() in ("run: |", "run: |-"))
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for ln in lines[start + 1:]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            break
        body.append(ln)
    return textwrap.dedent("\n".join(body))


def _job_level_conditions() -> list[str]:
    """`if:` lines belonging to the job itself, not to any of its steps."""
    header = _text().split("\n    steps:\n", 1)[0]
    return [ln.strip()[len("if:"):].strip() for ln in header.splitlines() if ln.strip().startswith("if:")]


# ---------------------------------------------------------------------------
# The bypass itself
# ---------------------------------------------------------------------------


def test_no_step_can_declare_the_review_unnecessary():
    """No skip flag, in any spelling.

    The mechanism was `echo "skip=true" >> $GITHUB_OUTPUT` read back as
    `if: steps.skip_check.outputs.skip != 'true'`. Cost control is legitimate;
    doing it with a flag that also satisfies the gate is not. If re-review of
    unchanged content needs suppressing again, it has to go through the verdict
    step, which knows the difference between "reviewed" and "not reviewed".
    """
    text = _text()
    offenders = [
        line.strip()
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
        and re.search(r"outputs\.skip\b|\bskip=(true|false)\b", line)
    ]
    assert offenders == [], (
        "a skip flag is back in ai-review.yml — skipping the reviewer must not "
        f"be expressible as a passing state:\n  " + "\n  ".join(offenders)
    )


def test_the_verdict_step_is_last_and_runs_whatever_happened_before_it():
    steps = _steps()
    assert VERDICT_STEP in steps[-1], f"{VERDICT_STEP!r} must be the last step in the job"

    condition = re.search(r"^\s*if:\s*(.+)$", steps[-1], re.MULTILINE)
    assert condition, f"{VERDICT_STEP!r} has no `if:` — it would inherit the implicit success()"
    assert re.search(r"!\s*cancelled\(\)|always\(\)", condition.group(1)), (
        f"{VERDICT_STEP!r} must run even when an earlier step failed or was skipped, "
        f"otherwise every path that never reaches the reviewer ends green. Found: {condition.group(1)!r}"
    )


def test_the_verdict_step_denies_by_default():
    script = _run_script(_step(VERDICT_STEP))
    assert re.search(r"^\s*\*\)", script, re.MULTILINE), (
        "the verdict step's case statement has no default branch — an outcome "
        "nobody anticipated would fall through and exit 0"
    )
    default = script.split("*)", 1)[1]
    assert "exit 1" in default.split(";;", 1)[0], "the default branch must fail closed"


# ---------------------------------------------------------------------------
# The same behaviour, executed rather than read
# ---------------------------------------------------------------------------


def _gate(diff_lines: str, review_outcome: str) -> int:
    """Run the verdict step's real shell body under the two inputs it reads."""
    return subprocess.run(
        ["bash", "-c", _run_script(_step(VERDICT_STEP))],
        env={"PATH": "/usr/bin:/bin", "DIFF_LINES": diff_lines, "REVIEW_OUTCOME": review_outcome},
        capture_output=True,
        text=True,
    ).returncode


@pytest.mark.parametrize(
    "diff_lines,review_outcome,reason",
    [
        ("420", "failure", "verdict was Review required, or the reviewer crashed"),
        ("420", "skipped", "the reviewer never ran — the shape of the old bypass"),
        ("420", "", "the reviewer never ran and reported nothing at all"),
        ("420", "cancelled", "the reviewer was interrupted mid-run"),
        ("420", "success ", "an outcome string nobody anticipated"),
        ("", "", "the diff step itself failed, so nothing downstream ran"),
        ("", "skipped", "no diff and no review"),
    ],
)
def test_the_gate_blocks_without_a_verdict(diff_lines, review_outcome, reason):
    assert _gate(diff_lines, review_outcome) == 1, f"gate passed when {reason}"


@pytest.mark.parametrize(
    "diff_lines,review_outcome",
    [("420", "success"), ("0", "skipped"), ("0", "")],
)
def test_the_gate_passes_only_on_a_reviewed_or_empty_diff(diff_lines, review_outcome):
    """The two legitimate greens: the reviewer returned a passing verdict, or
    the PR contains no reviewable code at all (docs, images, lockfiles)."""
    assert _gate(diff_lines, review_outcome) == 0


# ---------------------------------------------------------------------------
# The other ways a gate fails open
# ---------------------------------------------------------------------------


def test_the_diff_excludes_known_inert_files_rather_than_allow_listing_code():
    """An allow-list of extensions silently drops what nobody added to it.

    The list was source languages only, so a PR changing just a Dockerfile,
    Vault .hcl, JSON config or a .js file diffed to nothing and went green
    without a review. Exclusion means an unfamiliar file type gets reviewed by
    default, and an empty diff genuinely means there was no code in the PR.
    """
    script = _run_script(_step("Collect the PR's cumulative diff"))
    diff_cmd = script.split("git diff origin/main...HEAD", 1)[1].split(">", 1)[0]

    assert re.search(r"^\s*--\s+\.\s*\\?$", diff_cmd, re.MULTILINE), (
        "the diff must start from the whole tree (`-- .`) and subtract from it"
    )
    included = [g for g in re.findall(r"'([^']+)'", diff_cmd) if not g.startswith(":!")]
    assert included == [], f"these pathspecs allow-list file types instead of excluding them: {included}"


def test_only_the_reviewer_tolerates_its_own_failure():
    """`continue-on-error` on the review step is deliberate — a crash there
    should still post an explanatory comment before the job fails. Anywhere
    else it is a step whose failure stops mattering."""
    for step in _steps():
        # The key itself, at step indentation — the phrase also appears inside
        # a script comment explaining why the review step carries it.
        if re.search(r"^ {8}continue-on-error:\s*true\s*$", step, re.MULTILINE):
            assert "name: Run Claude review" in step, (
                f"continue-on-error outside the review step swallows a real failure:\n{step}"
            )


def test_conditional_steps_still_stop_when_something_upstream_broke():
    """An explicit `if:` replaces the implicit `success()`.

    `if: steps.diff.outputs.lines != '0'` alone would run the reviewer even
    after the diff step failed, on whatever /tmp/pr_diff.txt happened to hold.
    """
    for step in _steps():
        if VERDICT_STEP in step:
            continue
        condition = re.search(r"^\s*if:\s*(.+)$", step, re.MULTILINE)
        if condition:
            assert "success()" in condition.group(1), (
                f"step condition drops the implicit success() guard: {condition.group(1)!r}"
            )


def test_the_job_has_one_exemption_and_it_is_dependabot():
    """A skipped job counts as a passing required check, so a job-level `if:`
    is a bypass by another name. Dependabot is the one defensible case — those
    PRs get no secrets, so the review cannot run — and it must stay the only one."""
    assert _job_level_conditions() == ["github.actor != 'dependabot[bot]'"], (
        "the review job grew a new job-level condition; a skipped job reports as "
        "success to branch protection, so this is a way to be green without a review"
    )


def test_the_gate_has_no_shell_bypasses():
    offenders = [
        ln.strip() for ln in _text().splitlines()
        if "|| true" in ln and not ln.lstrip().startswith("#")
    ]
    assert offenders == [], f"`|| true` in the review gate: {offenders}"
